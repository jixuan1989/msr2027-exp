#!/usr/bin/env python3
"""Create complete-case inputs for the Paper 1 experiments.

``unknown`` is a missing-label state in the current working annotations, not a
substantive actor class.  This script therefore removes unknown actor-label
rows and every network event whose source identity cannot be resolved to a
known actor/provenance type.  The raw AIDev-derived files are never modified;
the filtered files and a manifest are written to a separate directory.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


KNOWN_ACTOR_TYPES = {
    "human_user",
    "llm_agent_account",
    "automation_bot",
    "service_account",
    "organization",
}
KNOWN_PROVENANCE_TYPES = KNOWN_ACTOR_TYPES | {"llm_agent_label"}


def norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def write_filtered_labels(source: Path, target: Path, actor_types: dict[str, str]) -> dict[str, int]:
    pf = pq.ParquetFile(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(target, pf.schema_arrow)
    counts = Counter(total=0, kept=0, dropped_unknown=0, dropped_blank_key=0)
    try:
        for batch in pf.iter_batches(batch_size=65_536, use_threads=False):
            data = batch.to_pydict()
            keep: list[int] = []
            for i, (key_raw, typ_raw) in enumerate(zip(data["actor_key"], data["actor_type"])):
                counts["total"] += 1
                key, typ = norm(key_raw), norm(typ_raw)
                if not key:
                    counts["dropped_blank_key"] += 1
                    continue
                actor_types[key] = typ
                if typ not in KNOWN_ACTOR_TYPES:
                    counts["dropped_unknown"] += 1
                    continue
                keep.append(i)
                counts["kept"] += 1
            if keep:
                filtered = {name: [values[i] for i in keep] for name, values in data.items()}
                writer.write_table(pa.Table.from_pydict(filtered, schema=pf.schema_arrow))
    finally:
        writer.close()
    return dict(counts)


def write_filtered_network(source: Path, target: Path, actor_types: dict[str, str]) -> dict[str, int]:
    pf = pq.ParquetFile(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(target, pf.schema_arrow)
    counts = Counter(total=0, kept=0, dropped_unknown=0, dropped_blank_source=0)
    try:
        for batch in pf.iter_batches(batch_size=65_536, use_threads=False):
            data = batch.to_pydict()
            keep: list[int] = []
            resolved_types: list[str] = []
            for i, (node_raw, type_raw) in enumerate(zip(data["source_node"], data["source_type"])):
                counts["total"] += 1
                node, supplied = norm(node_raw), norm(type_raw)
                if not node:
                    counts["dropped_blank_source"] += 1
                    continue
                resolved = supplied
                if not resolved and node.startswith("actor:"):
                    resolved = actor_types.get(node[6:], "")
                # ``llm_agent_label`` is provenance metadata, not an unknown
                # actor label; it is retained for traceability.
                if resolved not in KNOWN_PROVENANCE_TYPES:
                    counts["dropped_unknown"] += 1
                    continue
                keep.append(i)
                resolved_types.append(resolved)
                counts["kept"] += 1
            if keep:
                filtered = {name: [values[i] for i in keep] for name, values in data.items()}
                # Make source_type explicit for rows whose type was recovered
                # from actor_labels, without changing the raw input files.
                filtered["source_type"] = resolved_types
                writer.write_table(pa.Table.from_pydict(filtered, schema=pf.schema_arrow))
    finally:
        writer.close()
    return dict(counts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", type=Path, required=True)
    ap.add_argument("--network", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    actor_types: dict[str, str] = {}
    label_counts = write_filtered_labels(
        args.labels_dir / "actor_labels.parquet",
        args.out_dir / "actor_labels.parquet",
        actor_types,
    )
    network_counts = write_filtered_network(
        args.network,
        args.out_dir / "actor_pr_events.parquet",
        actor_types,
    )
    # PR labels contain no actor_type column; retain a byte-identical copy only
    # when present so the filtered directory remains self-contained.
    pr_source = args.labels_dir / "pr_labels.parquet"
    if pr_source.exists():
        pq.write_table(pq.read_table(pr_source), args.out_dir / "pr_labels.parquet")
    manifest = {
        "policy": "drop all rows with unknown or unresolved source identity; retain known actor and llm_agent_label provenance rows",
        "known_actor_types": sorted(KNOWN_ACTOR_TYPES),
        "known_provenance_types": sorted(KNOWN_PROVENANCE_TYPES),
        "actor_labels": label_counts,
        "network": network_counts,
        "inputs": {"labels_dir": str(args.labels_dir), "network": str(args.network)},
    }
    (args.out_dir / "unknown_filter_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
