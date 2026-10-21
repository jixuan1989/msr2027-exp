#!/usr/bin/env python3
"""Recompute the final All-known/Human-only community comparison."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from statistics import mean, pstdev
import community_core as core

ROOT = Path(__file__).resolve().parents[1]


def run(edges: Path, out: Path, seeds: list[int]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows, roles = core.load_edges(edges)
    graphs = {}
    for name, allowed in [("all-known", core.KNOWN_TYPES), ("human-only", {"human_user"})]:
        active, _ = core.active_accounts(rows, allowed)
        selected = [r for r in rows if r[0] in active]
        weights = core.make_edges(selected, roles, allowed, False)
        graph, nodes = core.make_graph(weights)
        graphs[name] = graph, nodes
    common = set(graphs["human-only"][1]) & {
        actor for actor, _, kind, _, _ in rows if kind == "human_user"}
    comparisons = []
    sizes = {}
    for seed in seeds:
        partitions = {}
        for name, (graph, nodes) in graphs.items():
            membership = core.leiden(graph, seed)
            partitions[name] = core.account_partition(nodes, membership)
            sizes.setdefault(name, {**core.summarize(nodes, membership), "edges": graph.ecount()})
            if seed == 42:
                graph.vs["membership_seed42"] = membership
                graph.write_pickle(str(out / f"{name}.pickle"))
        record = {"seed": seed, **core.pair_metrics(
            partitions["all-known"], partitions["human-only"], common)}
        comparisons.append(record)
        print(json.dumps({"stage": "seed_complete", **record}), flush=True)
    summary = {
        "experiment": "RQ1", "seeds": seeds, "common_humans": len(common),
        "scopes": sizes, "per_seed": comparisons,
        "nmi": {"mean": mean(r["nmi"] for r in comparisons),
                "sd": pstdev(r["nmi"] for r in comparisons)},
        "ari": {"mean": mean(r["ari"] for r in comparisons),
                "sd": pstdev(r["ari"] for r in comparisons)},
        "weighting": "One unit per retained participation event; repeated events accumulate.",
        "activity_rule": "An account must participate in an author-interactor pair within the same account scope.",
        "standard_deviation": "population standard deviation across the listed seeds",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (out / "per_seed.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(comparisons[0]))
        writer.writeheader(); writer.writerows(comparisons)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--role-edges", type=Path, default=ROOT / "outputs/role_aware_network/edges.parquet")
    p.add_argument("--out-dir", type=Path, default=ROOT / "outputs/rq1")
    p.add_argument("--seeds", type=int, nargs="+", default=list(core.SEEDS_DEFAULT))
    a = p.parse_args(); run(a.role_edges, a.out_dir, a.seeds)


if __name__ == "__main__":
    main()
