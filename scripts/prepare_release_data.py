#!/usr/bin/env python3
"""Export field-minimized, full-row experimental inputs retaining public IDs.

Example::
    python scripts/prepare_release_data.py --events /data/actor_pr_events.parquet \
      --labels /data/actor_labels.parquet --out-dir data/processed

All retained field values, including public account identifiers, login names,
repository URLs, PR/repository IDs, timestamps, and row order, are unchanged.
This script performs column selection and Parquet recompression only. It does
not create aliases, reversible maps, or additional account classifications.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from itertools import zip_longest
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


EVENT_COLUMNS = [
    "pr_id", "repo_id", "repo_url", "agent", "source_node", "target_node",
    "source_type", "target_type", "relation", "event", "event_time",
    "direct_user_type", "evidence_source",
]
LABEL_COLUMNS = ["actor_key", "login", "actor_type", "actor_subtype"]
BATCH = 131_072


def fingerprint(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": h.hexdigest(),
            "rows": pq.ParquetFile(path).metadata.num_rows}


def export_columns(source: Path, destination: Path, columns: list[str]) -> int:
    pf = pq.ParquetFile(source)
    schema = pa.schema([pf.schema_arrow.field(name) for name in columns])
    temporary = destination.with_name(destination.name + ".tmp")
    count = 0
    with pq.ParquetWriter(temporary, schema, compression="zstd") as writer:
        for batch in pf.iter_batches(batch_size=BATCH, columns=columns, use_threads=False):
            writer.write_table(pa.Table.from_batches([batch], schema=schema))
            count += batch.num_rows
    original = pf.iter_batches(batch_size=BATCH, columns=columns, use_threads=False)
    exported = pq.ParquetFile(temporary).iter_batches(
        batch_size=BATCH, columns=columns, use_threads=False)
    checked = 0
    for old_batch, new_batch in zip_longest(original, exported):
        if old_batch is None or new_batch is None or not old_batch.equals(new_batch):
            raise AssertionError("Retained values or row order changed during field selection")
        checked += old_batch.num_rows
    if checked != count or count != pf.metadata.num_rows:
        raise AssertionError("Row count changed during export")
    temporary.replace(destination)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    outputs = {(args.out_dir / name).resolve()
               for name in ("actor_pr_events.parquet", "actor_labels.parquet")}
    if args.events.resolve() in outputs or args.labels.resolve() in outputs:
        parser.error("Input files must not be overwritten by the release export")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    event_path = args.out_dir / "actor_pr_events.parquet"
    labels_path = args.out_dir / "actor_labels.parquet"
    event_rows = export_columns(args.events, event_path, EVENT_COLUMNS)
    label_rows = export_columns(args.labels, labels_path, LABEL_COLUMNS)

    pr_ids, repo_ids, account_sources, tool_sources = set(), set(), set(), set()
    source_types, evidence_sources, label_types = Counter(), Counter(), Counter()
    for batch in pq.ParquetFile(event_path).iter_batches(
            batch_size=BATCH, columns=["pr_id", "repo_id", "source_node", "source_type", "evidence_source"],
            use_threads=False):
        d = batch.to_pydict()
        pr_ids.update(d["pr_id"])
        repo_ids.update(d["repo_id"])
        account_sources.update(value for value in d["source_node"] if value.startswith("actor:"))
        tool_sources.update(value for value in d["source_node"] if value.startswith("agent:"))
        source_types.update(d["source_type"])
        evidence_sources.update(d["evidence_source"])
    for batch in pq.ParquetFile(labels_path).iter_batches(
            batch_size=BATCH, columns=["actor_type"], use_threads=False):
        label_types.update(batch.column(0).to_pylist())

    manifest = {
        "schema_version": "msr2027-field-minimized-public-input-v2",
        "source_fingerprints": {"events": fingerprint(args.events), "labels": fingerprint(args.labels)},
        "outputs": {"actor_pr_events.parquet": fingerprint(event_path),
                    "actor_labels.parquet": fingerprint(labels_path)},
        "event_columns": EVENT_COLUMNS, "label_columns": LABEL_COLUMNS,
        "account_label_rows": label_rows, "event_rows": event_rows,
        "repositories": len(repo_ids), "prs": len(pr_ids),
        "participating_account_identifiers": len(account_sources),
        "all_known_label_type_counts": dict(label_types),
        "event_source_type_counts": dict(source_types),
        "public_tool_source_identifiers": sorted(tool_sources),
        "evidence_source_enum": dict(evidence_sources),
        "export_policy": {
            "transformation": "Column selection and Parquet recompression only; no value changes.",
            "public_identifiers": "Original account keys, login names, PR/repository IDs, source/target node IDs, and repository URLs are retained.",
            "row_order": "All event and label rows remain in original order, without filtering, deduplication, aggregation, or sorting.",
            "timestamps_and_enums": "Original timestamps, account types, subtypes, relations, operations, user types, and source enums are unchanged.",
            "omitted_label_columns": "Original label evidence, source/count fields, and other columns outside LABEL_COLUMNS are omitted.",
            "aliasing": "None; no aliases or reversible mapping are generated.",
        },
        "checks": {
            "all_retained_event_values_and_row_order_exact": True,
            "all_retained_label_values_and_row_order_exact": True,
            "event_rows_preserved": True, "label_rows_preserved": True,
            "public_identifiers_logins_and_repo_urls_preserved": True,
            "no_alias_or_mapping_created": True,
        },
        "source_note": "The canonical inputs derive from the public AIDev dataset. This export retains the public identifiers and URLs needed to inspect the original records.",
    }
    manifest_path = args.out_dir / "release_data_manifest.json"
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    print(json.dumps({"event_rows": event_rows, "label_rows": label_rows,
                      "repositories": len(repo_ids), "prs": len(pr_ids),
                      "outputs": manifest["outputs"], "checks_passed": True}, indent=2))


if __name__ == "__main__":
    main()
