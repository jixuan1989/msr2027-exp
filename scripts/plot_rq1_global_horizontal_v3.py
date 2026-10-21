#!/usr/bin/env python3
"""Compare the saved complete RQ1 graphs within one paper column.

Reuse the full weighted graph's coordinates and complete-graph memberships.
Produce matched central zooms with titles and full-graph counts inside each
panel. No locator thumbnails, graph or membership changes are introduced.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import sys

import igraph as ig
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import numpy as np

from plot_helpers import graph_signature, sha256, match_colours, portable_metadata

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = PROJECT / "data/plot/rq1_global"
DEFAULT_CACHE = PROJECT / "data/plot/rq1_global/full_graph_fr_seed42_passes34.npz"
DEFAULT_OUT = PROJECT / "outputs/figures"


def draw(ax, graph, xy, rgb, limits, *, locator=False):
    pairs = np.asarray(graph.get_edgelist(), dtype=np.int32)
    ax.add_collection(LineCollection(
        xy[pairs], colors=(.24, .24, .24, .055 if not locator else .035),
        linewidths=.035 if not locator else .018, antialiased=True,
        rasterized=True, zorder=1))
    account = np.asarray(graph.vs["node_type"]) == "account"
    kinds = np.asarray(graph.vs["account_type"])
    selections = {
        "pr": (~account, .018 if not locator else .005, .80, "o"),
        "human": (account & (kinds == "human_user"), .15 if not locator else .027, .97, "o"),
        "nonhuman": (account & (kinds != "human_user"), .35 if not locator else .040, .97, "D"),
    }
    for _, (mask, size, alpha, marker) in selections.items():
        ax.scatter(xy[mask, 0], xy[mask, 1], s=size, c=rgb[mask],
                   alpha=alpha, marker=marker, linewidths=0,
                   rasterized=True, zorder=2)
    ax.set_xlim(limits[:2])
    ax.set_ylim(limits[2:])
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#d7dce2")
        spine.set_linewidth(.35)


def save(fig, out, stem, dpi):
    records = {}
    for ext in ("png", "pdf", "svg"):
        target = out / f"{stem}.{ext}"
        fig.savefig(target, dpi=dpi, facecolor="white")
        records[ext] = {"path": str(target), "bytes": target.stat().st_size,
                        "sha256": sha256(target)}
    plt.close(fig)
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--graph-dir", type=Path, default=DEFAULT_GRAPH)
    p.add_argument("--coordinates", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--half-span", type=float, default=.10)
    p.add_argument("--dpi", type=int, default=900)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.graph_dir / f"{name}.pickle" for name in ("I0R0", "I1R0")]
    full, human = [ig.Graph.Read_Pickle(str(path)) for path in paths]
    cache = np.load(args.coordinates, allow_pickle=False)
    metadata = json.loads(str(cache["metadata"]))
    assert metadata["graph_signature"] == graph_signature(full)
    assert np.array_equal(cache["names"], np.asarray(full.vs["name"]))
    xy = cache["xy"]
    hi, full_rgb, human_rgb, matches, common_count = match_colours(full, human, "membership_seed42")
    hxy = xy[hi]
    span = np.ptp(xy, axis=0)
    lower, upper = xy.min(axis=0) - .014 * span, xy.max(axis=0) + .014 * span
    limits = [float(lower[0]), float(upper[0]), float(lower[1]), float(upper[1])]
    # The viewport is set by all-node coordinate medians, never by the amount
    # of partition change. Its width is identical in the two panels.
    centre = np.median(xy, axis=0)
    focus = [float(centre[0] - args.half_span), float(centre[0] + args.half_span),
             float(centre[1] - args.half_span), float(centre[1] + args.half_span)]
    panel_data = [(full, xy, full_rgb, "(a) All accounts"),
                  (human, hxy, human_rgb, "(b) Human only")]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8,
                         "pdf.fonttype": 42, "svg.fonttype": "none"})
    outputs = {}
    for style, height in (("focus", 1.64),):
        fig = plt.figure(figsize=(3.42, height), facecolor="white")
        view_counts = []
        for column, (graph, coords, rgb, label) in enumerate(panel_data):
            x = .015 + column * .508
            bounds = [x, .010, .470, .980]
            ax = fig.add_axes(bounds)
            draw(ax, graph, coords, rgb, focus)
            # Overlay small labels inside the axes; they do not move vertices.
            label_box = dict(facecolor="white", edgecolor="none", alpha=.76, pad=1.1)
            ax.text(.025, .970, label, transform=ax.transAxes, fontsize=8,
                    va="top", ha="left", zorder=5, bbox=label_box)
            ax.text(.025, .030, f"{graph.vcount():,} nodes\n{graph.ecount():,} edges",
                    transform=ax.transAxes, fontsize=8, va="bottom", ha="left",
                    linespacing=1.25, zorder=5, bbox=label_box)
            inside = ((coords[:, 0] >= focus[0]) & (coords[:, 0] <= focus[1]) &
                      (coords[:, 1] >= focus[2]) & (coords[:, 1] <= focus[3]))
            view_counts.append({"graph": "I0R0" if column == 0 else "I1R0",
                                "total_nodes": graph.vcount(), "total_edges": graph.ecount(),
                                "nodes_in_zoom_window": int(inside.sum()),
                                "zoom_node_fraction": float(inside.mean())})
        outputs[style] = save(fig, args.out_dir, f"fig_rq1_global_horizontal_{style}_v3", args.dpi)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "command": shlex.join(["python", str(Path(__file__).resolve().relative_to(PROJECT)), *sys.argv[1:]]),
        "script": {"path": str(Path(__file__).resolve()), "sha256": sha256(__file__)},
        "inputs": [{"path": str(path), "sha256": sha256(path)} for path in paths],
        "coordinate_cache": {"path": str(args.coordinates), "sha256": sha256(args.coordinates),
                             "metadata": metadata},
        "memberships": "saved full graph Leiden modularity, seed42; never recomputed",
        "common_humans": common_count,
        "colour_matching": "one-to-one maximum overlap on common humans, reused from previous figure",
        "colour_matches": matches,
        "coordinate_reuse_exact": bool(np.array_equal(hxy, xy[hi])),
        "layout_unchanged": True, "aspect": "equal", "node_sampling": False,
        "edge_sampling": False, "synthetic_edges": False,
        "viewport_choice": "all-node coordinate median, fixed half-span; no choice using partition differences",
        "zoom_limits": focus, "full_limits": limits, "view_counts": view_counts,
        "main_zoom": "all graph primitives drawn and clipped to shared viewport; no graph subset or algorithm rerun; overlay labels may visually cover a small area",
        "full_locator": False,
        "overlay_labels": {"font_pt": 8, "top_left": "panel letter and account scope", "bottom_left": "full-graph node and edge totals", "background_alpha": .76},
        "figure_inches": {"focus": [3.42, 1.64]},
        "height_change_vs_previous_3_70_inches": {"focus": 1.64/3.70-1},
        "height_change_vs_v2_2_30_inches": 1.64/2.30-1,
        "marker_semantics": "tiny circles PR, larger circles human accounts, diamonds nonhuman accounts",
        "interpretation_limit": "full-network visual overview, not an individually readable community map or causal evidence",
        "dpi": args.dpi, "outputs": outputs,
    }
    report = portable_metadata(report, PROJECT)
    (args.out_dir / "fig_rq1_global_horizontal_focus_v3.manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.out_dir / "fig_rq1_global_horizontal_focus_v3.command.txt").write_text(report["command"]+"\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("view_counts", "figure_inches", "zoom_limits")}, indent=2))


if __name__ == "__main__":
    main()
