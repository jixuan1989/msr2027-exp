#!/usr/bin/env python3
"""Audit raw entity counts corresponding to the saved Paper 1 input scope.

Reproduce build_aidev_network.py's account resolver before applying the same
known-identity policy. Keep raw commit identity (repository, SHA), which is not
present in the expanded actor--PR file. This script does not alter any input or
rebuild a graph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

KNOWN = {"human_user", "llm_agent_account", "automation_bot", "service_account", "organization"}


def norm(value):
    text = "" if value is None else str(value).strip()
    return text[:-2] if re.fullmatch(r"-?\d+\.0", text) else text


def rows(path, columns):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=columns):
        yield from batch.to_pylist()


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    label_rows = pq.read_table(args.labels).to_pylist()
    key_to_type = {r["actor_key"]: r["actor_type"] for r in label_rows}
    login_to_key = {}
    for r in label_rows:
        login = norm(r.get("login")).lower()
        if login and login not in login_to_key:
            login_to_key[login] = r["actor_key"]

    def resolve(login=None, user_id=None):
        uid = f"id:{norm(user_id)}" if norm(user_id) else ""
        if uid and uid in key_to_type:
            return uid
        low = norm(login).lower()
        if low in login_to_key:
            return login_to_key[low]
        return f"login:{low}" if low else "login:unknown"

    def is_known(login=None, user_id=None):
        return key_to_type.get(resolve(login, user_id), "unknown") in KNOWN

    source_files = ["pull_request.parquet", "pr_commits.parquet", "pr_comments.parquet", "pr_reviews.parquet", "pr_review_comments.parquet"]
    manifest = {
        "method": "Reproduce source account resolution and known-identity filtering; count raw IDs independently of expanded participation rows.",
        "inputs": {"dataset": str(args.data_dir), "labels": str(args.labels), "labels_sha256": sha256(args.labels)},
        "schemas": {},
        "raw_file_metadata": {},
    }
    for name in source_files:
        pf = pq.ParquetFile(args.data_dir / name)
        manifest["schemas"][name] = {f.name: str(f.type) for f in pf.schema_arrow}
        manifest["raw_file_metadata"][name] = {"rows": pf.metadata.num_rows, "sha256": sha256(args.data_dir / name)}

    prs = {}
    known_pr_authors = set()
    for r in rows(args.data_dir / "pull_request.parquet", ["id", "repo_id", "repo_url", "user", "user_id"]):
        if r["id"] is None:
            continue
        pid = int(r["id"])
        prs[pid] = {"repo_id": r["repo_id"], "repo_url": r["repo_url"]}
        if is_known(r["user"], r["user_id"]):
            known_pr_authors.add(pid)
    manifest["scope"] = {
        "pull_requests": len(prs), "pull_requests_with_known_author": len(known_pr_authors),
        "repositories": len({r["repo_id"] for r in prs.values() if r["repo_id"] is not None}),
        "issues_used_in_saved_network": 0,
        "note": "PR scope comes from the enriched pull_request table used by the network builder. Issue tables were not used by that builder.",
    }

    cc = Counter()
    commit_pr_sha = set()
    commit_repo_sha = set()
    commit_sha = set()
    raw_pr_sha = set()
    raw_repo_sha = set()
    for r in rows(args.data_dir / "pr_commits.parquet", ["sha", "pr_id", "author", "committer"]):
        cc["raw_rows"] += 1
        pid = r["pr_id"]
        if pid not in prs:
            cc["outside_pr_scope"] += 1
            continue
        repo = prs[pid]["repo_id"]
        sha = norm(r["sha"])
        if sha:
            raw_pr_sha.add((pid, sha))
            raw_repo_sha.add((repo, sha))
        keep_author = bool(r["author"]) and is_known(r["author"])
        distinct_committer = bool(r["committer"]) and norm(r["committer"]).lower() != norm(r["author"]).lower()
        keep_committer = distinct_committer and is_known(r["committer"])
        cc["known_author_participation_rows"] += int(keep_author)
        cc["known_distinct_committer_participation_rows"] += int(keep_committer)
        if keep_author or keep_committer:
            cc["retained_raw_commit_rows"] += 1
            if repo is None:
                cc["retained_missing_repo_id"] += 1
            if not sha:
                cc["retained_missing_sha"] += 1
                continue
            commit_pr_sha.add((pid, sha))
            commit_repo_sha.add((repo, sha))
            commit_sha.add(sha)
        else:
            cc["dropped_no_known_participant"] += 1
    manifest["commits"] = dict(cc) | {
        "retained_missing_sha": cc["retained_missing_sha"],
        "retained_missing_repo_id": cc["retained_missing_repo_id"],
        "raw_distinct_pr_sha": len(raw_pr_sha), "raw_distinct_repo_sha": len(raw_repo_sha),
        "retained_distinct_pr_sha": len(commit_pr_sha), "retained_distinct_repo_sha": len(commit_repo_sha),
        "retained_distinct_sha": len(commit_sha),
        "account_participation_rows": cc["known_author_participation_rows"] + cc["known_distinct_committer_participation_rows"],
        "definition": "A retained raw commit has at least one known account participation retained by the original expansion. A unique repository commit is identified by (repo_id, sha), and a PR--commit association by (pr_id, sha).",
    }

    review_to_pr = {}
    for r in rows(args.data_dir / "pr_reviews.parquet", ["pr_id", "pull_request_review_id"]):
        if r["pr_id"] is not None and r["pull_request_review_id"] is not None:
            review_to_pr[int(r["pull_request_review_id"])] = int(r["pr_id"])

    for filename, kind, columns, pr_field, id_field in [
        ("pr_comments.parquet", "ordinary_comments", ["id", "pr_id", "user", "user_id"], "pr_id", "id"),
        ("pr_reviews.parquet", "reviews", ["id", "pr_id", "pull_request_review_id", "user"], "pr_id", "id"),
        ("pr_review_comments.parquet", "inline_review_comments", ["id", "pull_request_review_id", "user"], "pull_request_review_id", "id"),
    ]:
        count = Counter()
        ids = set()
        pr_ids = set()
        review_ids = set()
        for r in rows(args.data_dir / filename, columns):
            count["raw_rows"] += 1
            pid = r[pr_field] if pr_field == "pr_id" else review_to_pr.get(r[pr_field])
            if pid not in prs:
                count["outside_or_unresolved_pr_scope"] += 1
                continue
            if not is_known(r["user"], r.get("user_id")):
                count["dropped_unknown_account"] += 1
                continue
            count["retained_rows"] += 1
            pr_ids.add(pid)
            if r[id_field] is None:
                count["retained_missing_id"] += 1
            else:
                ids.add(r[id_field])
            if "pull_request_review_id" in r and r["pull_request_review_id"] is not None:
                review_ids.add(r["pull_request_review_id"])
        manifest[kind] = dict(count) | {"retained_unique_id": len(ids), "retained_unique_pr": len(pr_ids), "retained_missing_id": count["retained_missing_id"]}
        if kind == "reviews":
            manifest[kind]["retained_unique_pull_request_review_id"] = len(review_ids)
    manifest["comment_total"] = {
        "ordinary_comment_ids": manifest["ordinary_comments"]["retained_unique_id"],
        "inline_review_comment_ids": manifest["inline_review_comments"]["retained_unique_id"],
        "total_by_distinct_typed_id": manifest["ordinary_comments"]["retained_unique_id"] + manifest["inline_review_comments"]["retained_unique_id"],
        "definition": "Typed IDs keep ordinary and inline comments distinct. Formal reviews and duplicate timeline descriptions are not counted as comments.",
    }
    manifest["checks"] = {
        "expected_commit_author_rows": cc["known_author_participation_rows"] == 700176,
        "expected_commit_committer_rows": cc["known_distinct_committer_participation_rows"] == 19744,
        "expected_comment_rows": manifest["ordinary_comments"]["retained_rows"] == 373549,
        "expected_review_rows": manifest["reviews"]["retained_rows"] == 281152,
        "expected_inline_comment_rows": manifest["inline_review_comments"]["retained_rows"] == 289769,
        "retained_commit_sha_complete": cc["retained_missing_sha"] == 0,
        "retained_commit_repository_complete": cc["retained_missing_repo_id"] == 0,
        "ordinary_comment_id_complete": manifest["ordinary_comments"]["retained_missing_id"] == 0,
        "review_id_complete": manifest["reviews"]["retained_missing_id"] == 0,
        "inline_comment_id_complete": manifest["inline_review_comments"]["retained_missing_id"] == 0,
    }
    manifest["script_sha256"] = sha256(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k not in {"schemas", "raw_file_metadata"}}, ensure_ascii=False, indent=2))
    failures = [name for name, passed in manifest["checks"].items() if not passed]
    if failures:
        raise SystemExit("Raw inventory validation failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
