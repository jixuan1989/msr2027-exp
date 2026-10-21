#!/usr/bin/env python3
"""Render five monthly RQ3 metrics without recomputing experiments.

The first four panels read paired repository-month means.  The final panel
reads monthly PR-level median first-review waiting times.  Missing values
remain missing and line segments break at those months.  All 17 source
months are retained; repositories and PRs are never sampled by this script.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shlex
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.ticker import MaxNLocator
from plot_helpers import portable_metadata


WIDTH_IN = 3.42
HEIGHT_IN = 3.75
PNG_DPI = 600
STEM = "fig_rq3_monthly_metrics_v3"
COLORS = {"all": "#0072B2", "human": "#009E73"}
MONTHS = [f"{year:04d}-{month:02d}" for year, month in
          [(2024, 12), *[(2025, m) for m in range(1, 13)],
           *[(2026, m) for m in range(1, 5)]]]
PANELS = (
    ("active_accounts", "(a) Active accounts", "n_repos_active_accounts"),
    ("reviewer_count", "(b) Reviewers", "n_repos_reviewer_count"),
    ("review_hhi", "(c) HHI", "n_repos_review_hhi"),
    ("k50", r"(d) $k_{50}$", "n_repos_k50"),
    ("response_median_hours", "(e) First review (PR median hours)", None),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_or_none(value: float):
    return float(value) if math.isfinite(value) else None


def read_source(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if [row["month"] for row in rows] != MONTHS:
        raise ValueError("Expected each month from December 2024 to April 2026 exactly once.")
    series, denominators = {}, {}
    for key, _, repo_count_column in PANELS:
        series[key] = {}
        denominators[key] = {}
        for scope in ("all", "human"):
            column = f"{key}_{scope}"
            values = np.array([float(row[column]) if row[column].strip() else np.nan for row in rows])
            if np.any(np.isinf(values)) or np.any(values[np.isfinite(values)] < 0):
                raise ValueError(f"Invalid negative or infinite value in {column}.")
            if key == "review_hhi" and np.any(values[np.isfinite(values)] > 1):
                raise ValueError("HHI must lie within [0, 1].")
            count_column = repo_count_column or f"n_response_prs_{scope}"
            counts = [int(row[count_column]) for row in rows]
            for value, count in zip(values, counts):
                if (count > 0) != bool(np.isfinite(value)):
                    raise ValueError(f"Value/denominator mismatch in {column} and {count_column}.")
            series[key][scope] = values
            denominators[key][scope] = counts
    if any(np.isfinite(series["response_median_hours"][scope][-1]) for scope in ("all", "human")):
        raise ValueError("April 2026 first-review response should be missing in this snapshot.")
    return rows, series, denominators


def check_text(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    texts = [obj for obj in fig.findobj(Text) if obj.get_visible() and obj.get_text()]
    bounds = fig.bbox
    details = []
    for text in texts:
        box = text.get_window_extent(renderer)
        inside = bool(box.x0 >= bounds.x0-.2 and box.x1 <= bounds.x1+.2
                      and box.y0 >= bounds.y0-.2 and box.y1 <= bounds.y1+.2)
        details.append({"text": text.get_text(), "font_pt": text.get_fontsize(),
                        "inside_canvas": inside, "bbox_px": [float(v) for v in box.extents]})
    outside = [item["text"] for item in details if not item["inside_canvas"]]
    overlaps = []
    for i, left in enumerate(texts):
        a = left.get_window_extent(renderer)
        for right in texts[i+1:]:
            b = right.get_window_extent(renderer)
            dx = min(a.x1, b.x1) - max(a.x0, b.x0)
            dy = min(a.y1, b.y1) - max(a.y0, b.y0)
            if dx > .3 and dy > .3:
                overlaps.append({"texts": [left.get_text(), right.get_text()],
                                 "intersection_px": [float(dx), float(dy)]})
    if outside or overlaps:
        raise ValueError(json.dumps({"outside_canvas": outside, "text_overlaps": overlaps}, ensure_ascii=False))
    minimum = min(item["font_pt"] for item in details)
    if minimum < 8:
        raise ValueError("Visible text must be at least 8 points.")
    return {"minimum_visible_text_pt": minimum, "text_outside_canvas": outside,
            "text_overlaps": overlaps, "text_items": details}


def draw(series):
    rc = {
        "font.family": "Times New Roman", "font.size": 8,
        "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.fontsize": 8, "axes.linewidth": .55,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "svg.hashsalt": STEM, "figure.dpi": 150,
        "figure.facecolor": "white", "axes.facecolor": "white",
    }
    with plt.rc_context(rc):
        fig = plt.figure(figsize=(WIDTH_IN, HEIGHT_IN))
        positions = [(0.17, .745, .31, .175), (.655, .745, .31, .175),
                     (.17, .435, .31, .175), (.655, .435, .31, .175),
                     (.17, .125, .795, .175)]
        axes = [fig.add_axes(position) for position in positions]
        x = np.arange(len(MONTHS))
        line_checks = []
        for index, (ax, (key, title, _)) in enumerate(zip(axes, PANELS)):
            for scope in ("all", "human"):
                expected = series[key][scope]
                line, = ax.plot(x, expected, color=COLORS[scope],
                                ls="-" if scope == "all" else "--",
                                lw=1.05, marker="s" if scope == "all" else "o",
                                ms=2.5, mew=.35, zorder=3)
                exact = bool(np.array_equal(np.asarray(line.get_ydata()), expected, equal_nan=True))
                if not exact:
                    raise ValueError(f"Plotted values differ from source: {key}, {scope}.")
                line_checks.append({"metric": key, "scope": scope,
                                    "csv_values_exact": exact,
                                    "months_drawn": len(x),
                                    "finite_months": int(np.isfinite(expected).sum())})
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(axis="y", lw=.45, color="#dfe3e7", zorder=0)
            ax.set_axisbelow(True)
            ax.tick_params(axis="both", length=2.4, width=.55, pad=2)
            ax.set_xlim(-.45, len(MONTHS)-.55)
            if key == "review_hhi":
                ax.set_ylim(0, 1.04)
                ax.set_yticks([0, .5, 1], labels=["0", "0.5", "1"])
            else:
                available = np.concatenate([series[key][scope][np.isfinite(series[key][scope])]
                                            for scope in ("all", "human")])
                upper = float(available.max()) if len(available) else 1
                ax.set_ylim(0, upper*1.13 if upper > 0 else 1)
                ax.yaxis.set_major_locator(MaxNLocator(nbins=3, min_n_ticks=3, prune="upper"))
            if index < 4:
                ax.set_ylabel("Repo mean", labelpad=3)
                ax.set_xticks([0, 8, 16], labels=["Dec24", "Aug25", "Apr26"])
                caption_y = .67 if index < 2 else .36
            else:
                ax.set_ylabel("Hours", labelpad=3)
                ax.set_xticks([0, 4, 8, 12, 16],
                              labels=["Dec\n2024", "Apr\n2025", "Aug\n2025", "Dec\n2025", "Apr\n2026"])
                caption_y = .022
            # Keep endpoint date labels within their panel.  Their tick
            # locations still mark the exact first and last source months.
            date_labels = ax.get_xticklabels()
            date_labels[0].set_horizontalalignment("left")
            date_labels[-1].set_horizontalalignment("right")
            box = ax.get_position()
            fig.text((box.x0+box.x1)/2, caption_y, title, ha="center", va="center", fontsize=8)
        handles = [Line2D([], [], color=COLORS[scope], lw=1.15,
                          ls="-" if scope == "all" else "--",
                          marker="s" if scope == "all" else "o", ms=3,
                          label="All accounts" if scope == "all" else "Human-only")
                   for scope in ("all", "human")]
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.54, .995),
                   ncol=2, frameon=False, handlelength=2, handletextpad=.45,
                   columnspacing=1.25, borderpad=0)
        quality = check_text(fig)
    return fig, quality, line_checks


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "data/plot/rq3_monthly.csv")
    parser.add_argument("--out", type=Path, default=root / f"outputs/figures/{STEM}")
    args = parser.parse_args()
    source, base = args.input.resolve(), args.out.resolve()
    rows, series, denominators = read_source(source)
    fig, quality, line_checks = draw(series)
    base.parent.mkdir(parents=True, exist_ok=True)
    for extension in ("pdf", "png", "svg"):
        fig.savefig(base.with_suffix("."+extension), dpi=PNG_DPI, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    caption = (
        "Monthly comparison of project collaboration and maintenance metrics. "
        "Panels (a)--(d) show equally weighted means over repositories valid under both account scopes within each month. "
        "Panel (e) shows PR-level median time to first submitted review, grouped by PR creation month. "
        "Coverage varies across months; missing response months remain missing without zero filling or interpolation."
    )
    command = shlex.join(["python", str(Path(__file__).resolve().relative_to(root)), *sys.argv[1:]])
    base.with_name(base.name+"_caption.txt").write_text(caption+"\n", encoding="utf-8")
    base.with_name(base.name+"_command.txt").write_text(command+"\n", encoding="utf-8")
    manifest = {
        "figure": STEM,
        "source": {"path": str(source), "sha256": sha256(source), "rows": len(rows)},
        "script": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "size_inches": [WIDTH_IN, HEIGHT_IN],
        "size_mm": [WIDTH_IN*25.4, HEIGHT_IN*25.4],
        "png_dpi": PNG_DPI,
        "layout": "2x2 first-four metrics and full-width final response panel",
        "months": MONTHS,
        "series": {key: {scope: [finite_or_none(v) for v in values]
                         for scope, values in scopes.items()}
                   for key, scopes in series.items()},
        "denominators": denominators,
        "plotted_series_checks": line_checks,
        "quality": quality,
        "aggregation": {
            "first_four": "Monthly means across the same repositories valid in both account scopes, separately for each metric.",
            "response": "Monthly PR-level median by PR creation month; All accounts and Human-only can have different valid PR sets.",
            "missing": "Preserved as NaN, line breaks, no zero filling or interpolation.",
            "resampling": False,
            "experiments_recomputed_by_plotter": False,
            "coverage": "Repository and PR coverage can vary by month; not an estimate of ecosystem-wide AI adoption.",
        },
        "caption": caption,
        "command": command,
        "environment": {"python": platform.python_version(), "matplotlib": matplotlib.__version__, "numpy": np.__version__},
        "outputs": {ext: {"path": str(base.with_suffix("."+ext)), "sha256": sha256(base.with_suffix("."+ext))}
                    for ext in ("pdf", "png", "svg")},
    }
    manifest = portable_metadata(manifest, root)
    manifest_path = base.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "size_mm": manifest["size_mm"],
                      "minimum_font_pt": quality["minimum_visible_text_pt"],
                      "text_overlaps": quality["text_overlaps"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
