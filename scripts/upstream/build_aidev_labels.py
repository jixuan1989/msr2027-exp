#!/usr/bin/env python3
"""Build reproducible actor and PR labels for AIDev-7.6M.

The AIDev ``agent`` field is treated as a high-confidence PR-level label. It
does *not* turn the GitHub ``user`` account into an AI account: AIDev records
the human developer/account associated with an agent-authored PR. The script
therefore emits both ``pr_agent`` and an account-level ``actor_type``.

Account labels use existing GitHub ``user_type`` values where available,
account suffixes, a small auditable service/agent lexicon, and AIDev's
``all_user`` table. Ambiguous identities are retained as ``unknown`` and are
placed in an LLM review queue rather than being guessed.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


AGENT_NAMES = {
    "OpenAI_Codex",
    "Copilot",
    "Claude_Code",
    "Cursor",
    "Google_Jules",
    "Devin",
}

LLM_ACCOUNT_PATTERNS = {
    "OpenAI_Codex": ("chatgpt-codex", "codex[bot]", "openai-codex"),
    "Copilot": ("copilot", "github-copilot"),
    "Claude_Code": ("claude", "anthropic"),
    "Cursor": ("cursor",),
    "Google_AI": ("gemini-code-assist", "google-code-assist", "google-labs-jules"),
    "Devin": ("devin",),
    "AI_Reviewer": ("cubic-dev-ai", "greptile", "coderabbit", "sourcery"),
}
SERVICE_PATTERNS = (
    "github-actions",
    "codecov",
    "dependabot",
    "renovate",
    "vercel",
    "netlify",
    "snyk",
    "sonarcloud",
    "semantic-release",
    "release-drafter",
)


def norm(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # Arrow may expose nullable integer columns from one table as doubles.
    if re.fullmatch(r"-?\d+\.0", text):
        text = text[:-2]
    return text


def key_for(login: str, user_id=None) -> str:
    uid = norm(user_id)
    return f"id:{uid}" if uid and uid.lower() not in {"nan", "none"} else f"login:{login.lower()}"


def agent_account(login: str) -> str | None:
    x = login.lower()
    for agent, patterns in LLM_ACCOUNT_PATTERNS.items():
        if any(p in x for p in patterns):
            return agent
    return None


def service_account(login: str) -> bool:
    x = login.lower()
    return any(p in x for p in SERVICE_PATTERNS)


def add_actor(
    actors: dict[str, dict],
    login,
    user_id=None,
    source: str = "",
    user_type: str | None = None,
    count: int = 1,
    agent: str | None = None,
) -> None:
    login = norm(login)
    if not login:
        return
    user_id = norm(user_id)
    key = key_for(login, user_id)
    rec = actors.setdefault(
        key,
        {
            "actor_key": key,
            "login": login,
            "actor_id": user_id,
            "sources": Counter(),
            "user_types": Counter(),
            "agent_prs": Counter(),
            "counts": Counter(),
        },
    )
    # Prefer a real login and ID if the first observation came from a display
    # name or a commit record.
    if len(login) > len(rec["login"]):
        rec["login"] = login
    if user_id and not rec["actor_id"]:
        rec["actor_id"] = user_id
    rec["sources"][source] += count
    if user_type:
        rec["user_types"][norm(user_type)] += count
    rec["counts"][source] += count
    if agent:
        rec["agent_prs"][agent] += count


def batches(path: Path, columns: list[str], batch_size: int = 262_144):
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=batch_size, columns=columns):
        yield batch.to_pydict()


def label_actor(rec: dict) -> dict:
    login = rec["login"]
    low = login.lower()
    bot_count = rec["user_types"].get("Bot", 0)
    user_count = rec["user_types"].get("User", 0)
    explicit_agent = agent_account(login)
    suffix_bot = low.endswith("[bot]")
    botish = bot_count > 0 or suffix_bot
    if explicit_agent and (botish or user_count == 0):
        label, subtype = "llm_agent_account", explicit_agent
        confidence = "high" if botish else "medium"
        evidence = ["curated_llm_account_lexicon"]
    elif bot_count > 0 or suffix_bot:
        if service_account(login):
            label, subtype = "service_account", "known_service"
        else:
            label, subtype = "automation_bot", "unresolved_bot"
        confidence = "high" if bot_count > 0 or suffix_bot else "medium"
        evidence = ["github_user_type=Bot" if bot_count else "login_suffix=[bot]"]
    elif user_count > 0:
        label, subtype, confidence = "human_user", "github_user", "high"
        evidence = ["github_user_type=User"]
        if explicit_agent:
            evidence.append("AI_name_hint_not_used_as_account_type")
    elif rec["sources"].get("all_user", 0) > 0:
        label, subtype, confidence = "human_user", "AIDev_all_user", "medium"
        evidence = ["AIDev_all_user_table"]
    elif rec["sources"].get("all_pull_request", 0) > 0:
        label, subtype, confidence = "human_user", "AIDev_PR_account", "medium"
        evidence = ["AIDev_PR_account"]
    else:
        label, subtype, confidence = "unknown", "unresolved", "low"
        evidence = []
    if rec["agent_prs"]:
        evidence.append("AIDev_agent_field_is_PR_level_not_account_type")
    if len(rec["user_types"]) > 1:
        confidence = "medium"
        evidence.append("conflicting_user_type_observations")
    return {
        "actor_key": rec["actor_key"],
        "login": rec["login"],
        "actor_id": rec["actor_id"] or None,
        "actor_type": label,
        "actor_subtype": subtype,
        "confidence": confidence,
        "evidence": ";".join(evidence),
        "sources": json.dumps(dict(rec["sources"]), sort_keys=True),
        "user_types": json.dumps(dict(rec["user_types"]), sort_keys=True),
        "agent_pr_counts": json.dumps(dict(rec["agent_prs"]), sort_keys=True),
        "pr_count": int(rec["counts"].get("all_pull_request", 0)),
        "comment_count": int(rec["counts"].get("pr_comments", 0)),
        "review_count": int(rec["counts"].get("pr_reviews", 0)),
        "review_comment_count": int(rec["counts"].get("pr_review_comments", 0)),
        "commit_author_count": int(rec["counts"].get("pr_commits_author", 0) + rec["counts"].get("pr_commit_details_author", 0)),
        "commit_committer_count": int(rec["counts"].get("pr_commits_committer", 0) + rec["counts"].get("pr_commit_details_committer", 0)),
        "timeline_actor_count": int(rec["counts"].get("pr_timeline_actor", 0)),
        "timeline_assignee_count": int(rec["counts"].get("pr_timeline_assignee", 0)),
    }


PR_SCHEMA = pa.schema(
    [
        ("pr_id", pa.int64()),
        ("repo_id", pa.int64()),
        ("pr_user", pa.string()),
        ("pr_user_id", pa.string()),
        ("agent", pa.string()),
        ("created_at", pa.string()),
        ("state", pa.string()),
        ("merged_at", pa.string()),
        ("author_mode", pa.string()),
        ("author_label_confidence", pa.string()),
        ("author_evidence", pa.string()),
        ("agent_node", pa.string()),
    ]
)


ACTOR_SCHEMA = pa.schema(
    [
        ("actor_key", pa.string()),
        ("login", pa.string()),
        ("actor_id", pa.string()),
        ("actor_type", pa.string()),
        ("actor_subtype", pa.string()),
        ("confidence", pa.string()),
        ("evidence", pa.string()),
        ("sources", pa.string()),
        ("user_types", pa.string()),
        ("agent_pr_counts", pa.string()),
        ("pr_count", pa.int64()),
        ("comment_count", pa.int64()),
        ("review_count", pa.int64()),
        ("review_comment_count", pa.int64()),
        ("commit_author_count", pa.int64()),
        ("commit_committer_count", pa.int64()),
        ("timeline_actor_count", pa.int64()),
        ("timeline_assignee_count", pa.int64()),
    ]
)


def write_rows(writer, schema, rows: list[dict]) -> None:
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))
        rows.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=131_072)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    actors: dict[str, dict] = {}
    pr_path = args.data_dir / "all_pull_request.parquet"
    pr_writer = pq.ParquetWriter(args.out_dir / "pr_labels.parquet", PR_SCHEMA, compression="zstd")
    pr_count = 0
    pr_agent_counts = Counter()
    pr_rows: list[dict] = []
    for d in batches(pr_path, ["id", "repo_id", "user", "user_id", "agent", "created_at", "state", "merged_at"], args.batch_size):
        for row in zip(*(d[c] for c in d)):
            rid, repo_id, user, uid, agent, created, state, merged = row
            user_text = norm(user)
            uid_text = norm(uid)
            agent_text = norm(agent)
            add_actor(actors, user_text, uid_text, "all_pull_request", agent=agent_text)
            pr_agent_counts[agent_text] += 1
            pr_rows.append(
                {
                    "pr_id": int(rid) if rid is not None else None,
                    "repo_id": int(repo_id) if repo_id is not None else None,
                    "pr_user": user_text or None,
                    "pr_user_id": uid_text or None,
                    "agent": agent_text or None,
                    "created_at": norm(created) or None,
                    "state": norm(state) or None,
                    "merged_at": norm(merged) or None,
                    "author_mode": "agent_authored" if agent_text in AGENT_NAMES else "unknown",
                    "author_label_confidence": "high" if agent_text in AGENT_NAMES else "low",
                    "author_evidence": "AIDev.agent",
                    "agent_node": f"agent:{agent_text}" if agent_text else None,
                }
            )
            pr_count += 1
        write_rows(pr_writer, PR_SCHEMA, pr_rows)
    pr_writer.close()

    # Small user table gives an independent, documented human-developer source.
    user_path = args.data_dir / "all_user.parquet"
    for d in batches(user_path, ["id", "login"], args.batch_size):
        for uid, login in zip(d["id"], d["login"]):
            add_actor(actors, norm(login), norm(uid), "all_user")

    def scan_simple(filename: str, columns: list[str], source: str, login_cols: list[tuple[str, str | None, str | None]]):
        path = args.data_dir / filename
        if not path.exists():
            return
        for d in batches(path, columns, args.batch_size):
            for values in zip(*(d[c] for c in columns)):
                record = dict(zip(columns, values))
                for login_col, type_col, source_override in login_cols:
                    login = record.get(login_col)
                    uid = record.get("user_id") if login_col == "user" else None
                    add_actor(actors, login, uid, source_override or source, record.get(type_col) if type_col else None)

    scan_simple("pr_comments.parquet", ["user", "user_id", "user_type"], "pr_comments", [("user", "user_type", None)])
    scan_simple("pr_reviews.parquet", ["user", "user_type"], "pr_reviews", [("user", "user_type", None)])
    scan_simple("pr_review_comments.parquet", ["user", "user_type"], "pr_review_comments", [("user", "user_type", None)])
    scan_simple("issue.parquet", ["user"], "issue", [("user", None, None)])
    scan_simple("pr_commits.parquet", ["author", "committer"], "pr_commits", [("author", None, "pr_commits_author"), ("committer", None, "pr_commits_committer")])
    scan_simple("pr_commit_details.parquet", ["author", "committer"], "pr_commit_details", [("author", None, "pr_commit_details_author"), ("committer", None, "pr_commit_details_committer")])
    scan_simple("pr_timeline.parquet", ["actor", "assignee"], "pr_timeline", [("actor", None, "pr_timeline_actor"), ("assignee", None, "pr_timeline_assignee")])

    actor_rows = [label_actor(x) for x in actors.values()]
    actor_rows.sort(key=lambda x: (-x["pr_count"], x["login"].lower()))
    actor_writer = pq.ParquetWriter(args.out_dir / "actor_labels.parquet", ACTOR_SCHEMA, compression="zstd")
    for i in range(0, len(actor_rows), 100_000):
        actor_writer.write_table(pa.Table.from_pylist(actor_rows[i : i + 100_000], schema=ACTOR_SCHEMA))
    actor_writer.close()

    unknown = [x for x in actor_rows if x["actor_type"] == "unknown"]
    queue = {
        "purpose": "LLM or human adjudication queue; never treat these as gold labels without review",
        "n": len(unknown),
        "fields": ["actor_key", "login", "actor_id", "evidence", "sources", "user_types", "agent_pr_counts"],
        "actors": unknown[:100_000],
    }
    (args.out_dir / "llm_review_queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "pr_rows": pr_count,
        "pr_agent_counts": dict(pr_agent_counts),
        "actors": len(actor_rows),
        "actor_type_counts": dict(Counter(x["actor_type"] for x in actor_rows)),
        "confidence_counts": dict(Counter(x["confidence"] for x in actor_rows)),
        "unknown_queue": len(unknown),
        "note": "AIDev.agent is PR-level evidence; it is not used to relabel the PR user account as an AI actor.",
    }
    (args.out_dir / "label_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
