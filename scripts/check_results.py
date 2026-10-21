#!/usr/bin/env python3
"""Compare a fresh full-data run against the original final-study results."""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, pstdev

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--result-dir", type=Path, default=ROOT / "outputs")
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()
    checks = []

    def equal(label, actual, expected, tolerance=1e-12):
        passed = (math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance)
                  if isinstance(expected, (float, int)) else actual == expected)
        checks.append({"check": label, "actual": actual, "expected": expected, "passed": passed})

    r1 = json.loads((a.result_dir / "rq1/summary.json").read_text())
    ref1 = json.loads((ROOT / "results/reference/rq1/summary.json").read_text())
    equal("RQ1.common_humans", r1["common_humans"], ref1["common_human_count"])
    for scope, cell in [("all-known", "I0R0"), ("human-only", "I1R0")]:
        for key in ["nodes", "edges", "account_nodes", "pr_nodes"]:
            equal(f"RQ1.{scope}.{key}", r1["scopes"][scope].get(key), ref1["graph_counts"][cell][key])
    expected_seeds = {r["seed"]: r for r in ref1["pairwise_identity_R0"]}
    equal("RQ1.per_seed_count", len(r1["per_seed"]), len(expected_seeds))
    equal("RQ1.per_seed_unique", len({r["seed"] for r in r1["per_seed"]}), len(expected_seeds))
    equal("RQ1.per_seed_set", {r["seed"] for r in r1["per_seed"]} == set(expected_seeds), True)
    for row in r1["per_seed"]:
        for metric in ("nmi", "ari"):
            equal(f"RQ1.seed{row['seed']}.{metric}", row[metric], expected_seeds[row["seed"]][metric])
    equal("RQ1.eight_seeds", set(r1["seeds"]) == set(expected_seeds), True)
    for metric in ("nmi", "ari"):
        expected_values = [r[metric] for r in expected_seeds.values()]
        equal(f"RQ1.summary.{metric}.mean", r1[metric]["mean"], mean(expected_values))
        equal(f"RQ1.summary.{metric}.sd", r1[metric]["sd"], pstdev(expected_values))
    import igraph as ig
    for scope, cell in [("all-known", "I0R0"), ("human-only", "I1R0")]:
        generated = ig.Graph.Read_Pickle(str(a.result_dir / "rq1" / f"{scope}.pickle"))
        plotted = ig.Graph.Read_Pickle(str(ROOT / "data/plot/rq1_global" / f"{cell}.pickle"))
        equal(f"RQ1.figure_graph.{scope}.vertex_order", generated.vs["name"] == plotted.vs["name"], True)
        equal(f"RQ1.figure_graph.{scope}.edges_and_order", generated.get_edgelist() == plotted.get_edgelist(), True)
        equal(f"RQ1.figure_graph.{scope}.edge_weights", generated.es["weight"] == plotted.es["weight"], True)
        equal(f"RQ1.figure_graph.{scope}.seed42_memberships", generated.vs["membership_seed42"] == plotted.vs["membership_seed42"], True)

    r2 = json.loads((a.result_dir / "rq2/summary.json").read_text())
    with (ROOT / "results/reference/rq2/reviewer_metrics.csv").open(newline="") as f:
        reference = {r["model"]: r for r in csv.DictReader(f)}
    equal("RQ2.eligible_prs", r2["eligible_prs"], 15899)
    equal("RQ2.repositories", r2["eligible_repositories"], 3012)
    equal("RQ2.model_count", len(r2["models"]), 2)
    equal("RQ2.model_set", {r["model"] for r in r2["models"]} == set(reference), True)
    for model in r2["models"]:
        expected = reference[model["model"]]
        for key in [*[f"hit@{k}" for k in (1, 3, 5, 10, 20)],
                    *[f"recall@{k}" for k in (1, 3, 5, 10, 20)], "mrr@10"]:
            equal(f"RQ2.{model['model']}.{key}", model[key], float(expected[key]))
    equal("RQ2.relative_human_order_preserved", r2["relative_human_order_exact_prs"], 15899)
    all_model = next(x for x in r2["models"] if x["model"] == "repo_frequency_all")
    equal("RQ2.nonhuman_top10_slots", all_model["top10_nonhuman_slots"], 23348)
    equal("RQ2.returned_top10_slots", all_model["top10_returned_slots"], 81576)

    r3 = json.loads((a.result_dir / "rq3/summary.json").read_text())
    ref3 = json.loads((ROOT / "results/reference/rq3/paired_metrics.json").read_text())
    for key, source_key in [("active_accounts", "active_accounts"), ("reviewer_count", "reviewer_count"),
                            ("review_hhi", "review_hhi"), ("k50", "bus_factor50")]:
        for dest, src in [("n_repos", "repo_pairs"), ("all_mean", "all_known_repo_mean"),
                          ("human_mean", "human_only_repo_mean"), ("paired_delta", "paired_delta_all_minus_human")]:
            equal(f"RQ3.{key}.{dest}", r3["paired_metrics"][key][dest], ref3[source_key][src])
    for scope, n, hours in [("all", 83074, .5266666666666666), ("human", 59694, 1.353888888888889)]:
        equal(f"RQ3.response.{scope}.n_prs", r3["first_review_response"][scope]["n_prs"], n)
        equal(f"RQ3.response.{scope}.median_hours", r3["first_review_response"][scope]["median_hours"], hours)
    with (a.result_dir / "rq3/monthly_metrics.csv").open(newline="") as f:
        actual_months = list(csv.DictReader(f))
    with (ROOT / "results/reference/rq3/monthly_metrics.csv").open(newline="") as f:
        expected_months = list(csv.DictReader(f))
    equal("RQ3.month_count", len(actual_months), 17)
    for actual, expected in zip(actual_months, expected_months):
        equal("RQ3.month.order", actual["month"], expected["month"])
        equal(f"RQ3.{actual['month']}.column_set", set(expected) <= set(actual), True)
        for key, expected_value in expected.items():
            if key == "month":
                continue
            if expected_value == "":
                equal(f"RQ3.{actual['month']}.{key}.missing", actual[key], "")
            else:
                equal(f"RQ3.{actual['month']}.{key}", float(actual[key]), float(expected_value))
    graph_manifest = a.result_dir / "role_aware_network/manifest.json"
    if graph_manifest.exists():
        counts = json.loads(graph_manifest.read_text())["counts"]
        for key, expected in [("event", 4222224), ("account", 45598), ("pull_request", 361296)]:
            equal(f"G_R.{key}_nodes", counts["nodes"][key], expected)
        for key in ("participates_as", "acts_on"):
            equal(f"G_R.{key}_edges", counts["edges"][key], 4222224)
    report = {"passed": all(c["passed"] for c in checks), "checks": len(checks),
              "failed": [c for c in checks if not c["passed"]], "details": checks}
    out = a.out or a.result_dir / "reproduction_checks.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
