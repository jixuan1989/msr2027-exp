"""Frozen-history reviewer functions used by the final RQ2.

Extracted verbatim from the study implementation; no bootstrap or auxiliary
rankers are run by the final-experiment entry point.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
import pyarrow.parquet as pq

REVIEW_RELATIONS = {"review", "review_comment"}


NONHUMAN_TYPES = {"llm_agent_account", "automation_bot", "service_account", "organization"}


KNOWN_TYPES = NONHUMAN_TYPES | {"human_user"}


UTC = timezone.utc


K_VALUES = (1, 3, 5, 10, 20)


def norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_time(value: Any) -> float | None:
    text = norm(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z") if ts is not None else None


def batches(path: Path, columns: list[str], size: int = 131_072):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=size, columns=columns, use_threads=False):
        yield batch.to_pydict()


@dataclass(frozen=True)
class PR:
    pr_id: int
    repo_id: int
    repo_url: str
    author: str
    created: float


@dataclass(frozen=True)
class Pair:
    pr_id: int
    repo_id: int
    reviewer: str
    reviewer_type: str
    event_time: float


def load_labels(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return actor type/login keyed by actor key (without ``actor:``)."""
    types: dict[str, str] = {}
    logins: dict[str, str] = {}
    cols = ["actor_key", "actor_type", "login"]
    for d in batches(path, cols, 65_536):
        for key, actor_type, login in zip(d["actor_key"], d["actor_type"], d["login"]):
            k = norm(key)
            if k and norm(actor_type) in KNOWN_TYPES:
                types[k] = norm(actor_type)
                if norm(login):
                    logins[k] = norm(login)
    return types, logins


def resolve_type(source_node: str, source_type: str, actor_types: dict[str, str]) -> str:
    supplied = norm(source_type)
    if supplied and supplied != "unknown":
        return supplied
    if source_node.startswith("actor:"):
        return actor_types.get(source_node[6:], "unknown")
    return supplied or "unknown"


def load_events(network: Path, actor_types: dict[str, str]) -> tuple[dict[int, PR], list[Pair], dict[str, int]]:
    """Load PR creation rows and deduplicated review/review-comment pairs."""
    prs: dict[int, PR] = {}
    # Temporary pair -> earliest event and most informative type.
    pair_first: dict[tuple[int, str], tuple[int, str, float]] = {}
    counts = Counter()
    cols = ["pr_id", "repo_id", "repo_url", "source_node", "source_type", "relation", "event_time"]
    for d in batches(network, cols):
        for values in zip(*(d[c] for c in cols)):
            pr_id_raw, repo_raw, repo_url, source, source_type, relation, when_raw = values
            try:
                pr_id, repo_id = int(pr_id_raw), int(repo_raw)
            except (TypeError, ValueError):
                counts["invalid_ids"] += 1
                continue
            source, relation = norm(source), norm(relation)
            when = parse_time(when_raw)
            if relation == "author":
                typ = resolve_type(source, norm(source_type), actor_types)
                if typ not in KNOWN_TYPES:
                    counts["unknown_author_dropped"] += 1
                    continue
                if not source or when is None:
                    counts["missing_pr_creation"] += 1
                    continue
                # There should be one author row per PR; retain the first stable row.
                prs.setdefault(pr_id, PR(pr_id, repo_id, norm(repo_url), source, when))
                continue
            if relation not in REVIEW_RELATIONS:
                continue
            counts["raw_review_rows"] += 1
            if not source or when is None:
                counts["missing_review_time_or_source"] += 1
                continue
            typ = resolve_type(source, norm(source_type), actor_types)
            if typ not in KNOWN_TYPES:
                counts["unknown_reviewer_dropped"] += 1
                continue
            key = (pr_id, source)
            old = pair_first.get(key)
            if old is None:
                pair_first[key] = (repo_id, typ, when)
            else:
                # Keep the earliest valid timestamp for temporal leakage
                # control, while allowing a later informative label to
                # replace an earlier ``unknown`` type.
                old_repo, old_typ, old_when = old
                chosen_type = typ if old_typ == "unknown" and typ != "unknown" else old_typ
                chosen_when = min(old_when, when)
                chosen_repo = old_repo if old_when <= when else repo_id
                pair_first[key] = (chosen_repo, chosen_type, chosen_when)
    pairs: list[Pair] = []
    for (pr_id, reviewer), (repo_id, typ, when) in pair_first.items():
        pr = prs.get(pr_id)
        if pr is None:
            counts["review_without_author_row"] += 1
            continue
        if when < pr.created:
            counts["review_before_pr_creation"] += 1
            continue
        if repo_id != pr.repo_id:
            counts["repo_id_mismatch_use_author_repo"] += 1
            repo_id = pr.repo_id
        pairs.append(Pair(pr_id, repo_id, reviewer, typ, when))
    counts["prs_with_creation"] = len(prs)
    counts["unique_pr_reviewer_pairs"] = len(pairs)
    return prs, pairs, dict(counts)


def _before(pr: PR, pair: Pair, cutoff: float) -> bool:
    return pr.created < cutoff and pair.event_time < cutoff


def build_histories(prs: dict[int, PR], pairs: Iterable[Pair], cutoff: float) -> dict[str, Any]:
    """Build frozen histories using only pre-cutoff PRs and review events."""
    repo_all: dict[int, Counter] = defaultdict(Counter)
    repo_human: dict[int, Counter] = defaultdict(Counter)
    affinity_human: dict[str, Counter] = defaultdict(Counter)
    authors: set[str] = set()
    repos: set[int] = set()
    used = 0
    for pair in pairs:
        pr = prs.get(pair.pr_id)
        if pr is None or not _before(pr, pair, cutoff):
            continue
        used += 1
        repos.add(pr.repo_id)
        authors.add(pr.author)
        repo_all[pr.repo_id][pair.reviewer] += 1
        if pair.reviewer_type == "human_user":
            repo_human[pr.repo_id][pair.reviewer] += 1
            affinity_human[pr.author][pair.reviewer] += 1
    return {"repo_all": repo_all, "repo_human": repo_human, "affinity_human": affinity_human,
            "authors": authors, "repos": repos, "used_pairs": used, "cutoff": cutoff}


def rank(counter: Counter | None, exclude: str, k: int | None = 10) -> list[str]:
    if not counter:
        return []
    ranked = [n for n, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])) if n != exclude]
    return ranked if k is None else ranked[:k]


def targets_for_pr(pr: PR, pairs_by_pr: dict[int, list[Pair]], horizon_days: int = 30) -> set[str]:
    end = pr.created + horizon_days * 86400
    return {p.reviewer for p in pairs_by_pr.get(pr.pr_id, [])
            if p.event_time >= pr.created and p.event_time < end and p.reviewer_type == "human_user" and p.reviewer != pr.author}


def _one_metric(ranking: list[str], target: set[str], ks: tuple[int, ...]) -> dict[str, float]:
    ranks = [ranking.index(x) + 1 for x in target if x in ranking]
    first = min(ranks) if ranks else None
    out: dict[str, float] = {"coverage": 1.0 if ranking else 0.0,
                             "mrr@10": 1.0 / first if first is not None and first <= 10 else 0.0}
    for k in ks:
        out[f"hit@{k}"] = 1.0 if first is not None and first <= k else 0.0
        out[f"recall@{k}"] = sum(1 for r in ranks if r <= k) / len(target) if target else 0.0
    return out


