#!/usr/bin/env python3
"""Compact RQ2 main-test Hit/Recall curves from existing micro metrics.

Only the final-test repo-frequency rows are read.  This script does not run
recommendation, fit/smooth curves, resample PRs, or change any experiment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import shlex
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.text import Text
from matplotlib.ticker import PercentFormatter
from plot_helpers import portable_metadata

K = (1, 3, 5, 10, 20)
MODELS = ("repo_frequency_all", "repo_frequency_human")
LABELS = ("All accounts", "Human-only")
COLORS = ("#0072B2", "#009E73")
WIDTH_IN, HEIGHT_IN = 3.42, 1.50


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", type=Path, default=root / "data/plot/rq2_curves.csv")
    ap.add_argument("--out", type=Path, default=root / "outputs/figures/fig_reviewer_identity_k_compact_v2")
    args = ap.parse_args()
    metrics = args.metrics.resolve()
    base = args.out.resolve()
    base.parent.mkdir(parents=True, exist_ok=True)
    with metrics.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    chosen = []
    for model, label in zip(MODELS, LABELS):
        matched = [r for r in rows if r["split"] == "final_test" and r["scope"] == "micro" and r["model"] == model]
        if len(matched) != 1:
            raise ValueError(f"Expected one final-test micro row for {model}")
        row = matched[0]
        record = {"split": row["split"], "scope": row["scope"], "model": model,
                  "label": label, "n_prs": int(row["n_prs"]), "n_repos": int(row["n_repos"]),
                  "values": {m: [float(row[f"{m}@{k}"]) for k in K] for m in ("hit", "recall")}}
        if any(not 0 <= v <= 1 for vals in record["values"].values() for v in vals):
            raise ValueError("Metric outside [0, 1]")
        chosen.append(record)
    if {(r["n_prs"], r["n_repos"]) for r in chosen} != {(15899, 3012)}:
        raise ValueError("Expected the 15,899 PR / 3,012 repository main test")

    style = {"font.family": "DejaVu Sans", "font.size": 8, "axes.labelsize": 8,
             "axes.titlesize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
             "legend.fontsize": 8, "pdf.fonttype": 42, "ps.fonttype": 42,
             "svg.fonttype": "none", "axes.linewidth": .6,
             "savefig.dpi": 600, "figure.facecolor": "white", "axes.facecolor": "white"}
    with plt.rc_context(style):
        fig = plt.figure(figsize=(WIDTH_IN, HEIGHT_IN))
        axes = [fig.add_axes((.10, .255, .365, .49)),
                fig.add_axes((.61, .255, .365, .49))]
        for ax, metric, title in zip(axes, ("hit", "recall"), ("(a) Hit@k", "(b) Recall@k")):
            for i, record in enumerate(chosen):
                ax.plot(K, record["values"][metric], color=COLORS[i],
                        linestyle="-" if i == 0 else "--", marker="o" if i == 0 else "s",
                        markersize=2.6, markeredgewidth=.4, linewidth=1.0,
                        label=record["label"], zorder=3-i)
            ax.set_xlim(.0, 21)
            ax.set_ylim(.25, .675)
            ax.set_xticks(K)
            ax.set_yticks((.3, .4, .5, .6))
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.tick_params(axis="both", length=2.2, width=.6, pad=1.6)
            ax.grid(axis="y", color="#dfdfdf", linewidth=.45, zorder=0)
            ax.set_title(title, pad=3)
            ax.spines[["top", "right"]].set_visible(False)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.54, 1.012),
                   ncol=2, frameon=False, handlelength=1.8, handletextpad=.5,
                   columnspacing=1.0, borderpad=0)
        fig.text(.54, .04, "Top-k list length", ha="center", va="bottom", fontsize=8)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        canvas = fig.bbox
        text_checks = []
        for obj in fig.findobj(match=Text):
            if not obj.get_visible() or not obj.get_text():
                continue
            bbox = obj.get_window_extent(renderer)
            inside = bbox.x0 >= canvas.x0 - .1 and bbox.x1 <= canvas.x1 + .1 and bbox.y0 >= canvas.y0 - .1 and bbox.y1 <= canvas.y1 + .1
            text_checks.append({"text": obj.get_text(), "font_pt": obj.get_fontsize(), "inside_canvas": inside})
        if not all(r["inside_canvas"] for r in text_checks):
            raise ValueError(f"Text outside fixed figure canvas: {[r for r in text_checks if not r['inside_canvas']]}")
        tick_overlap_checks = []
        for ax in axes:
            boxes = [t.get_window_extent(renderer) for t in ax.get_xticklabels() if t.get_visible()]
            tick_overlap_checks.extend(a.x1 <= b.x0 for a, b in zip(boxes, boxes[1:]))
        if not all(tick_overlap_checks):
            raise ValueError("Adjacent x tick labels overlap")
        for ext in ("pdf", "png", "svg"):
            fig.savefig(base.with_suffix("." + ext), dpi=600, bbox_inches=None, pad_inches=0)
        plt.close(fig)

    command = shlex.join(["python", str(Path(__file__).resolve().relative_to(root)), *sys.argv[1:]])
    outputs = {ext: {"path": str(base.with_suffix("." + ext)), "sha256": digest(base.with_suffix("." + ext))} for ext in ("pdf", "png", "svg")}
    manifest = {
        "script": str(Path(__file__).resolve()), "script_sha256": digest(Path(__file__)),
        "reproduce_command": command, "input": {"path": str(metrics), "sha256": digest(metrics), "rows": len(rows)},
        "runtime": {"python": platform.python_version(), "matplotlib": matplotlib.__version__},
        "layout": {"width_inches": WIDTH_IN, "height_inches": HEIGHT_IN,
                   "width_mm": WIDTH_IN * 25.4, "height_mm": HEIGHT_IN * 25.4,
                   "minimum_font_pt": min(r["font_pt"] for r in text_checks),
                   "fixed_page_size_no_tight_crop": True, "png_dpi": 600,
                   "panels": "Main-test Hit@k and Recall@k side by side; shared top legend.",
                   "all_visible_text_inside_canvas": all(r["inside_canvas"] for r in text_checks),
                   "adjacent_x_tick_labels_do_not_overlap": all(tick_overlap_checks),
                   "y_limits": [.25, .675], "y_axis": "Percent scale explicitly labelled; zero baseline not shown."},
        "k_values": list(K), "plotted_rows": chosen,
        "data_contract": {"weighting": "Existing micro metrics: eligible PRs equally weighted.",
                          "changed_experiments": False, "new_sampling": False, "new_interpolation_or_smoothing": False,
                          "validation_panels_removed": "User-edited RQ2 discusses only the Jan–Feb 2026 main test."},
        "comparison_to_previous": {"previous_height_inches": 6.4,
                                   "new_height_at_equal_width_3_42_in": HEIGHT_IN,
                                   "previous_height_at_equal_width_3_42_in": 6.4 * WIDTH_IN / 3.5,
                                   "height_reduction_fraction_at_equal_width": 1 - HEIGHT_IN / (6.4 * WIDTH_IN / 3.5)},
        "outputs": outputs,
    }
    manifest = portable_metadata(manifest, root)
    base.with_name(base.name + "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base.with_name(base.name + "_reproduce_command.txt").write_text(command + "\n", encoding="utf-8")
    print(json.dumps({"base": str(base), "size_mm": [WIDTH_IN*25.4, HEIGHT_IN*25.4],
                      "height_reduction_fraction": manifest["comparison_to_previous"]["height_reduction_fraction_at_equal_width"],
                      "input_sha256": digest(metrics)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
