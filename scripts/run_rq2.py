#!/usr/bin/env python3
"""Recompute the final fixed-cutoff reviewer results, without resampling."""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
import reviewer_core as core

ROOT = Path(__file__).resolve().parents[1]


def run(events: Path, labels: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    types, _ = core.load_labels(labels)
    prs, pairs, load_counts = core.load_events(events, types)
    by_pr = defaultdict(list)
    for pair in pairs:
        by_pr[pair.pr_id].append(pair)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()
    hist = core.build_histories(prs, pairs, start)
    candidate_types = {pair.reviewer: pair.reviewer_type for pair in pairs}
    rows = defaultdict(list); slots = Counter(); nonhuman = Counter()
    eligible_repos = set(); eligible_count = 0; order_checks = 0
    for pr in prs.values():
        if not start <= pr.created < end:
            continue
        target = core.targets_for_pr(pr, by_pr, 30)
        if not target:
            continue
        eligible_count += 1; eligible_repos.add(pr.repo_id)
        full = core.rank(hist["repo_all"].get(pr.repo_id), pr.author, None)
        human = core.rank(hist["repo_human"].get(pr.repo_id), pr.author, None)
        filtered = [x for x in full if candidate_types.get(x) == "human_user"]
        if filtered != human:
            raise AssertionError("Relative human candidate order changed.")
        order_checks += 1
        for model, ranking in [("repo_frequency_all", full), ("repo_frequency_human", human)]:
            row = core._one_metric(ranking[:20], target, core.K_VALUES)
            row.update(pr_id=pr.pr_id, repo_id=pr.repo_id, candidate_count=len(ranking))
            rows[model].append(row)
            slots[model] += len(ranking[:10])
            nonhuman[model] += sum(candidate_types.get(x) != "human_user" for x in ranking[:10])
    metrics = []
    for model, observations in rows.items():
        record = {"split": "final_test", "scope": "micro", "model": model,
                  "n_prs": len(observations), "n_repos": len(eligible_repos),
                  "candidate_count_mean": fmean(x["candidate_count"] for x in observations),
                  "candidate_count_median": __import__("statistics").median(x["candidate_count"] for x in observations)}
        for key in ["coverage", *[f"hit@{k}" for k in core.K_VALUES],
                    *[f"recall@{k}" for k in core.K_VALUES], "mrr@10"]:
            record[key] = fmean(x[key] for x in observations)
        record["top10_nonhuman_slot_share"] = nonhuman[model] / slots[model] if slots[model] else 0
        record["top10_returned_slots"] = slots[model]
        record["top10_nonhuman_slots"] = nonhuman[model]
        metrics.append(record)
    with (out / "reviewer_metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(metrics[0]))
        writer.writeheader(); writer.writerows(metrics)
    summary = {"experiment": "RQ2", "history_cutoff": "2026-01-01T00:00:00Z",
               "test_window": ["2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"],
               "target_horizon_days": 30, "eligible_prs": eligible_count,
               "eligible_repositories": len(eligible_repos), "models": metrics,
               "relative_human_order_exact_prs": order_checks, "load_counts": load_counts,
               "aggregation": "Arithmetic mean over all eligible PRs; no sampling or bootstrap.",
               "tie_break": "Descending historical distinct-PR review count, then ascending account key.",
               "target": "Observed human reviewers within 30 days, excluding the PR author."}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"stage": "rq2_complete", "eligible_prs": eligible_count,
                      "eligible_repositories": len(eligible_repos), "models": metrics}), flush=True)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events", type=Path, default=ROOT / "data/processed/actor_pr_events.parquet")
    p.add_argument("--labels", type=Path, default=ROOT / "data/processed/actor_labels.parquet")
    p.add_argument("--out-dir", type=Path, default=ROOT / "outputs/rq2")
    a = p.parse_args(); run(a.events, a.labels, a.out_dir)


if __name__ == "__main__":
    main()
