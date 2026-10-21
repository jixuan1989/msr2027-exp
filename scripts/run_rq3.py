#!/usr/bin/env python3
"""Recompute the final paired maintenance metrics and monthly curves."""
from __future__ import annotations
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean
import paper1_governance_metrics as core

ROOT = Path(__file__).resolve().parents[1]
METRICS = {
    "active_accounts": ("active_accounts_all", "active_accounts_human"),
    "reviewer_count": ("reviewer_count_all", "reviewer_count_human"),
    "review_hhi": ("review_hhi_all", "review_hhi_human"),
    "k50": ("review_bus_factor50_all", "review_bus_factor50_human"),
}


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def value(text):
    return None if text in {"", "None", "null", None} else float(text)


def run(events: Path, labels: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    saved = sys.argv
    try:
        sys.argv = ["paper1_governance_metrics.py", "--network", str(events),
                    "--labels", str(labels), "--out-dir", str(out / "cells")]
        core.main()
    finally:
        sys.argv = saved
    cells = read_csv(out / "cells/governance_repo_month.csv")
    base = json.loads((out / "cells/governance_summary.json").read_text())
    months = sorted({r["month"] for r in cells})
    monthly = {m: {"month": m} for m in months}; metrics = {}
    for name, (all_col, human_col) in METRICS.items():
        by_repo = defaultdict(lambda: {"all": [], "human": []})
        for month in months:
            pairs = [r for r in cells if r["month"] == month
                     and value(r[all_col]) is not None and value(r[human_col]) is not None]
            monthly[month][f"n_repos_{name}"] = len(pairs)
            for scope, col in [("all", all_col), ("human", human_col)]:
                monthly[month][f"{name}_{scope}"] = fmean(float(r[col]) for r in pairs) if pairs else None
                for row in pairs:
                    by_repo[int(row["repo_id"])][scope].append(float(row[col]))
        pairs = [(fmean(v["all"]), fmean(v["human"])) for v in by_repo.values()]
        metrics[name] = {"n_repos": len(pairs),
                         "all_mean": fmean(x[0] for x in pairs),
                         "human_mean": fmean(x[1] for x in pairs),
                         "paired_delta": fmean(x[0] - x[1] for x in pairs)}
    prs = {}; first = {"all": {}, "human": {}}
    cols = ["pr_id", "repo_id", "repo_url", "source_node", "source_type", "relation", "event_time"]
    for batch in core.batches(events, cols):
        for pid, rid, url, actor, kind, relation, when in zip(*(batch[c] for c in cols)):
            if relation != "author" or kind not in core.KNOWN_TYPES:
                continue
            ts = core.parse_ts(when)
            if ts is not None:
                prs.setdefault(int(pid), (int(rid), ts))
    for batch in core.batches(events, cols):
        for pid, rid, url, actor, kind, relation, when in zip(*(batch[c] for c in cols)):
            if relation != "review" or not actor or kind not in core.KNOWN_TYPES:
                continue
            ts = core.parse_ts(when); pr = prs.get(int(pid))
            if ts is None or pr is None or ts < pr[1]:
                continue
            for scope in ["all", *(["human"] if kind == "human_user" else [])]:
                first[scope][int(pid)] = min(ts, first[scope].get(int(pid), ts))
    response = {}; response_months = defaultdict(lambda: {"all": [], "human": []})
    for scope in ("all", "human"):
        hours = []
        for pid, ts in first[scope].items():
            duration = (ts - prs[pid][1]) / 3600
            hours.append(duration)
            response_months[core.month(prs[pid][1])][scope].append(duration)
        response[scope] = {"n_prs": len(hours), "median_hours": core.quant(hours, .5)}
    for month in months:
        for scope in ("all", "human"):
            values = response_months[month][scope]
            monthly[month][f"n_response_prs_{scope}"] = len(values)
            monthly[month][f"response_median_hours_{scope}"] = core.quant(values, .5)
    monthly_rows = list(monthly.values())
    with (out / "monthly_metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(monthly_rows[0]))
        writer.writeheader(); writer.writerows(monthly_rows)
    summary = {"experiment": "RQ3", "scope": base["scope"],
               "weighted_activity_share": base["weighted_activity_share"],
               "paired_metrics": metrics, "first_review_response": response,
               "months": months,
               "response_quantile": "sorted(values)[int(round(q*(n-1)))], as in the study implementation",
               "aggregation": "Pair valid repository-month cells, average within repository, then average repositories without weights.",
               "monthly_aggregation": "Paired repository means for the first four metrics; PR-level response medians grouped by PR creation month.",
               "sampling": "None; all eligible cells and responding PRs are used."}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"stage": "rq3_complete", **summary}), flush=True)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events", type=Path, default=ROOT / "data/processed/actor_pr_events.parquet")
    p.add_argument("--labels", type=Path, default=ROOT / "data/processed/actor_labels.parquet")
    p.add_argument("--out-dir", type=Path, default=ROOT / "outputs/rq3")
    a = p.parse_args(); run(a.events, a.labels, a.out_dir)


if __name__ == "__main__":
    main()
