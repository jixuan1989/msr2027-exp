#!/usr/bin/env python3
"""Read-only inventory of the saved experimental input and role-aware graph.

Raw artifact counts are computed separately by count_known_raw_records.py.
This script intentionally does not deduplicate events or change the network.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


def fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    prs, repositories, sources = set(), set(), set()
    relations, evidence = Counter(), Counter()
    input_rows = 0
    for batch in pq.ParquetFile(args.events).iter_batches(
            columns=["pr_id", "repo_id", "source_node", "relation", "evidence_source"]):
        data = batch.to_pydict()
        input_rows += batch.num_rows
        prs.update(data["pr_id"])
        repositories.update(data["repo_id"])
        sources.update(data["source_node"])
        relations.update(data["relation"])
        evidence.update(data["evidence_source"])

    node_types, account_types = Counter(), Counter()
    account_nodes, tool_nodes = set(), []
    for batch in pq.ParquetFile(args.nodes).iter_batches(
            columns=["node_id", "node_type", "actor_type"]):
        for key, node_type, actor_type in zip(*batch.to_pydict().values()):
            node_types[node_type] += 1
            if node_type == "account":
                account_nodes.add(key)
                account_types[actor_type] += 1
                if actor_type == "llm_agent_label":
                    tool_nodes.append(key)

    edge_types = Counter()
    nonunit_edges = 0
    for batch in pq.ParquetFile(args.edges).iter_batches(columns=["edge_type", "weight"]):
        data = batch.to_pydict()
        edge_types.update(data["edge_type"])
        nonunit_edges += sum(weight != 1 for weight in data["weight"])

    checks = {
        "input_sources_equal_account_nodes": sources == account_nodes,
        "one_event_node_per_input_row": node_types["event"] == input_rows,
        "one_pr_node_per_selected_pr": node_types["pull_request"] == len(prs),
        "two_edges_per_input_row": sum(edge_types.values()) == 2 * input_rows,
        "participates_as_count_matches_input": edge_types["participates_as"] == input_rows,
        "acts_on_count_matches_input": edge_types["acts_on"] == input_rows,
        "all_edge_weights_are_one": nonunit_edges == 0,
    }
    assert all(checks.values()), checks
    result = {
        "scope": "current saved experimental input; no cleaning or network rebuild",
        "inputs": {name: fingerprint(getattr(args, name)) for name in ("events", "nodes", "edges")},
        "selected_prs": len(prs), "selected_repositories": len(repositories),
        "input_records_D": input_rows, "node_counts": dict(node_types),
        "edge_counts": dict(edge_types), "account_types": dict(account_types),
        "account_identifier_nodes_excluding_tool_labels": len(account_nodes) - len(tool_nodes),
        "tool_label_nodes": sorted(tool_nodes), "relations": dict(relations),
        "evidence_sources": dict(evidence), "checks": checks,
        "interpretation": [
            "D and V_E count saved rows, not cross-source deduplicated real-world operations.",
            "V_A currently includes tool-label nodes which are not independent GitHub accounts.",
            "No Issue or Commit artifact nodes are saved; commits operate on PR artifacts.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "D": input_rows, "node_counts": dict(node_types),
                      "selected_repositories": len(repositories), "all_checks_passed": True}, indent=2))


if __name__ == "__main__":
    main()
