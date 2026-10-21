#!/usr/bin/env python3
"""Redraw experimental Figures 3--7 from the packaged analysis outputs.

No graph layout, community detection, or recommendation experiment is run.
The original graph ordering, cached coordinates, partitions, displayed public
case, and aggregate tables are checked before rendering. Original public-source
account and PR identifiers are retained in the plotting inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

import igraph as ig
import numpy as np
from PIL import Image

from plot_helpers import graph_signature, match_colours

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "3": ("plot_rq1_global_horizontal_v3.py", "fig_rq1_global_horizontal_focus_v3"),
    "4": ("plot_rq1_local_horizontal_v2.py", "fig_rq1_local_horizontal_v2"),
    "5": ("plot_reviewer_candidate_lists_v2.py", "fig_reviewer_candidate_lists_v2"),
    "6": ("plot_reviewer_identity_k_compact_v2.py", "fig_reviewer_identity_k_compact_v2"),
    "7": ("plot_rq3_monthly_metrics_v3.py", "fig_rq3_monthly_metrics_v3"),
}


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_fingerprint(graph):
    fields = ["node_type", "account_type", "common_human", "membership_seed42"]
    return digest_json({"vcount": graph.vcount(), "edges": graph.get_edgelist(),
                        "weights": graph.es["weight"],
                        "vertices": {field: graph.vs[field] for field in fields}})


def verify_inputs(expected, figures):
    checks = {}
    for name, record in expected["inputs"].items():
        assert file_sha(ROOT / name) == record["sha256"], f"Input changed: {name}"
    checks["packaged_table_hashes"] = True
    if "3" in figures:
        graph_dir = ROOT / "data/plot/rq1_global"
        graphs = {key: ig.Graph.Read_Pickle(str(graph_dir / f"{key}.pickle"))
                  for key in ("I0R0", "I1R0")}
        for key, graph in graphs.items():
            assert graph_fingerprint(graph) == expected["graphs"][key]["numeric_fingerprint"], key
            assert set(graph.vs.attributes()) == set(expected["graphs"][key]["required_vertex_attributes"]), key
            assert digest_json(graph.vs["name"]) == expected["graphs"][key]["source_name_fingerprint"]
        cached = np.load(graph_dir / "full_graph_fr_seed42_passes34.npz", allow_pickle=False)
        assert np.array_equal(cached["names"], np.asarray(graphs["I0R0"].vs["name"]))
        assert hashlib.sha256(cached["xy"].tobytes()).hexdigest() == expected["graphs"]["coordinates_sha256"]
        assert json.loads(str(cached["metadata"]))["graph_signature"] == graph_signature(graphs["I0R0"])
        colors = match_colours(graphs["I0R0"], graphs["I1R0"], "membership_seed42")
        for name, index in (("all", 1), ("human", 2)):
            assert hashlib.sha256(colors[index].tobytes()).hexdigest() == expected["graphs"]["color_arrays_sha256"][name]
        checks["rq1_graph_edges_weights_order_memberships_coordinates_colors"] = True
    if "5" in figures:
        panels = json.loads((ROOT / "data/plot/rq2_candidates/reviewer_candidate_audit.json").read_text())["final_test"]["example"]["panels"]
        content = {name: [{key: value for key, value in row.items() if key != "actor_key"}
                           for row in rows] for name, rows in panels.items()}
        assert digest_json(content) == expected["figures"]["rq2_candidate_display_fingerprint"]
        assert digest_json(panels) == expected["figures"]["rq2_candidate_source_fingerprint"]
        checks["rq2_public_case_rank_login_type_score_target_fields"] = True
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures", choices=list(SCRIPTS), nargs="+", default=list(SCRIPTS))
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/figures"),
                        help="Output directory, relative to the package root unless absolute.")
    args = parser.parse_args()
    selected = list(dict.fromkeys(args.figures))
    expected = json.loads((ROOT / "data/plot/figure_expectations.json").read_text())
    checks = verify_inputs(expected, selected)
    summary = {"entry_point": "python scripts/render_figures.py",
               "output_directory": str(args.out_dir), "figures": {},
               "input_checks": checks, "layout_or_experiment_recomputed": False,
               "runtime": {name: importlib.metadata.version(name)
                           for name in ("igraph", "matplotlib", "numpy", "scipy", "networkx", "pyarrow", "pillow")}}
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for number in selected:
        script, stem = SCRIPTS[number]
        print(f"Rendering Figure {number}: scripts/{script}", flush=True)
        output_argument = os.path.relpath(out_dir, ROOT)
        if number in ("3", "4", "5"):
            output_args = ["--out-dir", output_argument]
        else:
            output_args = ["--out", str(Path(output_argument) / stem)]
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *output_args],
                                   cwd=ROOT, text=True, capture_output=True)
        if completed.returncode:
            print(completed.stdout.replace(str(ROOT), "."), file=sys.stderr)
            print(completed.stderr.replace(str(ROOT), "."), file=sys.stderr)
            raise RuntimeError(f"Figure {number} renderer failed")
        png = out_dir / (stem + ".png")
        pixels = np.asarray(Image.open(png).convert("RGBA"))
        reference = expected["figures"][stem]
        pixel_hash = hashlib.sha256(pixels.tobytes()).hexdigest()
        record = {"content_checks_passed": True,
                  "rgba_shape": list(pixels.shape),
                  "reference_rgba_shape_match": list(pixels.shape) == reference["reference_rgba_shape"],
                  "reference_pixel_match": pixel_hash == reference["reference_pixel_sha256"],
                  "pixel_sha256": pixel_hash,
                  "outputs": {extension: {"path": os.path.relpath(out_dir / f"{stem}.{extension}", ROOT),
                                           "bytes": (out_dir / f"{stem}.{extension}").stat().st_size,
                                           "sha256": file_sha(out_dir / f"{stem}.{extension}")}
                              for extension in ("pdf", "png", "svg")}}
        assert record["reference_rgba_shape_match"], f"Figure {number} canvas size changed"
        if number == "4":
            manifest = json.loads((out_dir / (stem + ".manifest.json")).read_text())
            assert manifest["panel_stats"] == expected["figures"]["rq1_local_panel_stats"]
        if number == "7":
            manifest = json.loads((out_dir / (stem + ".manifest.json")).read_text())
            assert all(item["csv_values_exact"] for item in manifest["plotted_series_checks"])
        summary["figures"][number] = record
        print(f"Figure {number}: content verified; reference pixels match={record['reference_pixel_match']}", flush=True)
    (out_dir / "figure_generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
