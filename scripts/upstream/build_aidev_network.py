#!/usr/bin/env python3
"""Create an event-level actor--PR network from the AIDev-pop tables.

The network is represented as a heterogeneous edge list. PRs are explicit
artifact nodes, while ``agent:<name>`` nodes represent the AIDev agent label.
This avoids pretending that a human GitHub account is itself an AI account.
The resulting edge list can be projected to actor-only networks in later
experiments without losing the original evidence.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


EDGE_SCHEMA = pa.schema(
    [
        ("pr_id", pa.int64()),
        ("repo_id", pa.int64()),
        ("repo_url", pa.string()),
        ("agent", pa.string()),
        ("source_node", pa.string()),
        ("target_node", pa.string()),
        ("source_type", pa.string()),
        ("target_type", pa.string()),
        ("relation", pa.string()),
        ("event", pa.string()),
        ("event_time", pa.string()),
        ("direct_user_type", pa.string()),
        ("evidence_source", pa.string()),
    ]
)


def norm(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"-?\d+\.0", text):
        text = text[:-2]
    return text


def id_key(value) -> str:
    return f"id:{norm(value)}" if norm(value) else ""


def login_key(value) -> str:
    return f"login:{norm(value).lower()}" if norm(value) else ""


def actor_node(key: str) -> str:
    return f"actor:{key}"


def pr_node(pr_id) -> str:
    return f"pr:{int(pr_id)}"


def safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def batches(path: Path, columns: list[str], batch_size: int = 131_072):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size, columns=columns):
        yield batch.to_pydict()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--labels-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=131_072)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Actor labels are small enough to load fully and are used only for node
    # type metadata; raw evidence remains in actor_labels.parquet.
    actor_table = pq.read_table(args.labels_dir / "actor_labels.parquet")
    actor_rows = actor_table.to_pylist()
    key_to_type = {r["actor_key"]: r["actor_type"] for r in actor_rows}
    login_to_key: dict[str, str] = {}
    for r in actor_rows:
        login = norm(r.get("login")).lower()
        if login and login not in login_to_key:
            login_to_key[login] = r["actor_key"]

    def resolve(login=None, user_id=None, display=False) -> str:
        uid = id_key(user_id)
        if uid and uid in key_to_type:
            return uid
        low = norm(login).lower()
        if low in login_to_key:
            return login_to_key[low]
        if display:
            return f"display:{low}" if low else "display:unknown"
        return login_key(login) or "login:unknown"

    def type_for(node: str) -> str:
        if node.startswith("agent:"):
            return "llm_agent_label"
        if node.startswith("pr:"):
            return "pull_request"
        return key_to_type.get(node.removeprefix("actor:"), "unknown") if node.startswith("actor:") else "unknown"

    pr_meta: dict[int, dict] = {}
    repo_number_to_pr: dict[tuple[str, int], int] = {}
    pr_path = args.data_dir / "pull_request.parquet"
    for d in batches(pr_path, ["id", "number", "repo_id", "repo_url", "user", "user_id", "agent", "created_at", "state", "merged_at"], args.batch_size):
        for row in zip(*(d[c] for c in d)):
            rid, number, repo_id, repo_url, user, user_id, agent, created, state, merged = row
            rid = safe_int(rid)
            if rid is None:
                continue
            m = {
                "pr_id": rid,
                "number": safe_int(number),
                "repo_id": safe_int(repo_id),
                "repo_url": norm(repo_url),
                "user": norm(user),
                "user_id": norm(user_id),
                "agent": norm(agent),
                "created_at": norm(created) or None,
                "state": norm(state) or None,
                "merged_at": norm(merged) or None,
            }
            pr_meta[rid] = m
            if m["repo_url"] and m["number"] is not None:
                repo_number_to_pr[(m["repo_url"].rstrip("/").lower(), m["number"])] = rid

    review_to_pr: dict[int, int] = {}
    for d in batches(args.data_dir / "pr_reviews.parquet", ["pr_id", "pull_request_review_id"], args.batch_size):
        for pr_id, review_id in zip(d["pr_id"], d["pull_request_review_id"]):
            if pr_id is not None and review_id is not None:
                review_to_pr[int(review_id)] = int(pr_id)

    out_path = args.out_dir / "actor_pr_events.parquet"
    writer = pq.ParquetWriter(out_path, EDGE_SCHEMA, compression="zstd")
    buffer: list[dict] = []
    relation_counts = Counter()
    node_type_counts = Counter()

    def add_edge(pr_id, source, relation, event=None, event_time=None, direct_user_type=None, evidence=""):
        if pr_id is None or pr_id not in pr_meta or not source:
            return
        meta = pr_meta[pr_id]
        target = pr_node(pr_id)
        source_type = type_for(source)
        target_type = "pull_request"
        buffer.append(
            {
                "pr_id": pr_id,
                "repo_id": meta["repo_id"],
                "repo_url": meta["repo_url"] or None,
                "agent": meta["agent"] or None,
                "source_node": source,
                "target_node": target,
                "source_type": source_type,
                "target_type": target_type,
                "relation": relation,
                "event": norm(event) or None,
                "event_time": norm(event_time) or None,
                "direct_user_type": norm(direct_user_type) or None,
                "evidence_source": evidence,
            }
        )
        relation_counts[relation] += 1
        node_type_counts[source_type] += 1

    def flush():
        if buffer:
            writer.write_table(pa.Table.from_pylist(buffer, schema=EDGE_SCHEMA))
            buffer.clear()

    # Every enriched PR yields an explicit human/account edge and an agent edge.
    for meta in pr_meta.values():
        user = resolve(meta["user"], meta["user_id"])
        add_edge(meta["pr_id"], actor_node(user), "author", event="pr_opened", event_time=meta["created_at"], evidence="pull_request.user")
        if meta["agent"]:
            add_edge(meta["pr_id"], f"agent:{meta['agent']}", "agent_authored", event="agent_label", event_time=meta["created_at"], evidence="AIDev.agent")
        if len(buffer) >= 100_000:
            flush()

    def process_user_table(filename: str, columns: list[str], relation: str, pr_col: str = "pr_id", user_col: str = "user", id_col: str | None = "user_id", type_col: str | None = "user_type", time_col: str | None = None):
        path = args.data_dir / filename
        for d in batches(path, columns, args.batch_size):
            for values in zip(*(d[c] for c in columns)):
                rec = dict(zip(columns, values))
                pr_id = safe_int(rec.get(pr_col))
                source = actor_node(resolve(rec.get(user_col), rec.get(id_col)))
                add_edge(pr_id, source, relation, event=relation, event_time=rec.get(time_col) if time_col else None, direct_user_type=rec.get(type_col) if type_col else None, evidence=filename)
            if len(buffer) >= 100_000:
                flush()

    process_user_table("pr_comments.parquet", ["pr_id", "user", "user_id", "user_type", "created_at"], "comment", time_col="created_at")
    process_user_table("pr_reviews.parquet", ["pr_id", "user", "user_type", "state", "submitted_at"], "review", type_col="user_type", time_col="submitted_at")

    # Inline review comments are joined to PRs through the review ID. The
    # original table has no direct user_id, so login resolution is explicit.
    for d in batches(args.data_dir / "pr_review_comments.parquet", ["pull_request_review_id", "user", "user_type", "created_at"], args.batch_size):
        for values in zip(*(d[c] for c in ["pull_request_review_id", "user", "user_type", "created_at"])):
            review_id, user, user_type, created = values
            pr_id = review_to_pr.get(safe_int(review_id))
            source = actor_node(resolve(user, None))
            add_edge(pr_id, source, "review_comment", event="inline_review_comment", event_time=created, direct_user_type=user_type, evidence="pr_review_comments.parquet")
        if len(buffer) >= 100_000:
            flush()

    def process_commit_table(filename: str):
        path = args.data_dir / filename
        for d in batches(path, ["pr_id", "author", "committer"], args.batch_size):
            for pr_id, author, committer in zip(d["pr_id"], d["author"], d["committer"]):
                pr_id = safe_int(pr_id)
                if author:
                    add_edge(pr_id, actor_node(resolve(author, None)), "commit_author", event="commit", evidence=filename)
                if committer and norm(committer).lower() != norm(author).lower():
                    add_edge(pr_id, actor_node(resolve(committer, None)), "commit_committer", event="commit", evidence=filename)
            if len(buffer) >= 100_000:
                flush()

    process_commit_table("pr_commits.parquet")

    timeline_events = {
        "assigned",
        "unassigned",
        "review_requested",
        "review_request_removed",
        "reviewed",
        "commented",
        "committed",
        "merged",
        "copilot_work_started",
        "copilot_work_finished",
        "copilot_work_finished_failure",
        "labeled",
    }
    for d in batches(args.data_dir / "pr_timeline.parquet", ["pr_id", "event", "created_at", "actor", "assignee"], args.batch_size):
        for pr_id, event, created, actor, assignee in zip(d["pr_id"], d["event"], d["created_at"], d["actor"], d["assignee"]):
            event = norm(event)
            if event not in timeline_events:
                continue
            pr_id = safe_int(pr_id)
            if actor:
                add_edge(pr_id, actor_node(resolve(actor, None, display=True)), f"timeline_{event}", event=event, event_time=created, evidence="pr_timeline.actor")
            if assignee:
                add_edge(pr_id, actor_node(resolve(assignee, None, display=True)), "assignee", event=event, event_time=created, evidence="pr_timeline.assignee")
        if len(buffer) >= 100_000:
            flush()

    flush()
    writer.close()
    summary = {
        "enriched_prs": len(pr_meta),
        "review_id_mappings": len(review_to_pr),
        "edges_by_relation": dict(relation_counts),
        "edges": sum(relation_counts.values()),
        "source_type_counts": dict(node_type_counts),
        "note": "This is an evidence-preserving heterogeneous actor-to-PR network; project to actor-only networks only in downstream analyses.",
    }
    (args.out_dir / "network_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
