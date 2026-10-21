#!/usr/bin/env python3
"""Compact the saved real Reviewer example without recomputing candidates.

The saved Post-filter and Human-only row dictionaries must be exactly equal.
They share a display column, as in the previous single-column figure. Full
logins, ten ranks, account types and observed human target flags are retained.
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
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.textpath import TextPath


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/plot/rq2_candidates/reviewer_candidate_audit.json"
CSV = SOURCE.with_name("reviewer_candidate_audit_example.csv")
BASE = ROOT / "outputs/figures/fig_reviewer_candidate_lists_v2"
WIDTH_MM = 86.868
FONT_PT = 8.0
FAMILY = "DejaVu Sans"
PROPS = FontProperties(family=FAMILY, size=FONT_PT)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def text_width(label: str) -> float:
    return float(TextPath((0, 0), label, prop=PROPS).get_extents().width) if label else 0.0


def wrap_login(login: str, available_pt: float) -> str:
    """Wrap at a hyphen or character without abbreviating the account login."""
    original = login
    lines = []
    while text_width(login) > available_pt:
        last_fit = max(i for i in range(1, len(login) + 1)
                       if text_width(login[:i]) <= available_pt)
        preferred = login.rfind("-", 0, last_fit)
        cut = preferred + 1 if preferred >= last_fit // 2 else last_fit
        lines.append(login[:cut])
        login = login[cut:]
    lines.append(login)
    assert "".join(lines) == original
    return "\n".join(lines)


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=BASE.parent)
    args = parser.parse_args()
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    BASE = out_dir / BASE.name
    result = json.loads(SOURCE.read_text(encoding="utf-8"))
    example = result["final_test"]["example"]
    panels = example["panels"]
    with CSV.open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    for panel, rows in panels.items():
        saved = [r for r in csv_rows if r["panel"] == panel]
        if len(saved) != len(rows):
            raise ValueError(f"CSV and JSON lengths differ for {panel}")
        for rec, check in zip(rows, saved):
            if (int(check["rank"]), check["login"], check["actor_key"],
                check["actor_type"], int(check["score"]), check["is_target"] == "True") != (
                    rec["rank"], rec["login"], rec["actor_key"], rec["actor_type"],
                    rec["score"], rec["is_target"]):
                raise ValueError(f"CSV and JSON differ in {panel}, rank {rec['rank']}")
    if panels["post-filter"] != panels["human-only"]:
        raise ValueError("Post-filter and Human-only differ and cannot share a column")
    lists = [panels["all-known"], panels["human-only"]]
    for rows in lists:
        if [row["rank"] for row in rows] != list(range(1, 11)):
            raise ValueError("The complete original top ten must be retained")
    width = WIDTH_MM / 25.4 * 72
    margin, gutter = 5.0, 10.0
    panel_width = (width - 2 * margin - gutter) / 2
    label_offset, label_width = 21.0, panel_width - 22.0
    wrapped = [[wrap_login(str(row["login"]), label_width - (6 if row["is_target"] else 0))
                for row in rows] for rows in lists]
    line_pt, padding_pt = 9.0, 3.0
    heights = [max(wrapped[0][i].count("\n") + 1, wrapped[1][i].count("\n") + 1) * line_pt + padding_pt
               for i in range(10)]
    # Space is expressed in physical points so printed text remains exactly 8 pt.
    legend_top, header_y, rows_top = 4.0, 21.5, 33.0
    height = rows_top + sum(heights) + 21.0
    plt.rcParams.update({"font.family": FAMILY, "font.size": FONT_PT,
                         "pdf.fonttype": 42, "svg.fonttype": "none",
                         "svg.hashsalt": "paper1-reviewer-candidate-lists-v2"})
    fig = plt.figure(figsize=(width / 72, height / 72), dpi=600)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, width), ylim=(height, 0))
    ax.set_axis_off()
    colors = {"human_user": "#0072B2", "llm_agent_account": "#D55E00"}
    markers = {"human_user": "o", "llm_agent_account": "^"}
    handles = [Line2D([0], [0], color="none", marker="o", markersize=4,
                      markerfacecolor=colors["human_user"], markeredgecolor=colors["human_user"],
                      label="Human account"),
               Line2D([0], [0], color="none", marker="^", markersize=4,
                      markerfacecolor=colors["llm_agent_account"], markeredgecolor=colors["llm_agent_account"],
                      label="AI agent account")]
    ax.legend(handles=handles, ncol=2, frameon=False, fontsize=FONT_PT,
              loc="upper center", bbox_to_anchor=(.5, 1 - legend_top / height),
              columnspacing=1.0, handlelength=.8, handletextpad=.4,
              borderpad=0, borderaxespad=0)
    headers = ["All accounts", "Human-only = Post-filter"]
    for c, rows in enumerate(lists):
        left = margin + c * (panel_width + gutter)
        ax.text(left + panel_width / 2, header_y, headers[c],
                ha="center", va="center", weight="bold", fontsize=FONT_PT)
        y = rows_top
        for i, row in enumerate(rows):
            center = y + heights[i] / 2
            typ = row["actor_type"]
            if typ not in colors:
                raise ValueError(f"Unexpected account type: {typ}")
            if row["is_target"]:
                ax.add_patch(plt.Rectangle((left - .5, y + .3), panel_width + 1,
                                          heights[i] - .6, color="#eaf2f6", linewidth=0,
                                          zorder=0))
            ax.text(left + 7, center, str(row["rank"]), ha="right", va="center",
                    fontsize=FONT_PT, color="#4b4b4b")
            ax.scatter(left + 14, center, s=17, marker=markers[typ],
                       color=colors[typ], edgecolor="black" if row["is_target"] else colors[typ],
                       linewidth=.6, zorder=3)
            label = ("* " if row["is_target"] else "") + wrapped[c][i]
            ax.text(left + label_offset, center, label, va="center", linespacing=1.1,
                    fontsize=FONT_PT, color="#1b1b1b")
            y += heights[i]
    ax.plot([width / 2, width / 2], [header_y - 8, rows_top + sum(heights) - .5],
            color="#d4d4d4", linewidth=.5)
    ax.text(width / 2, height - 7.5, "* Actual human reviewer within 30 days",
            ha="center", va="center", fontsize=FONT_PT)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    objects = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text()]
    boxes = [t.get_window_extent(renderer) for t in objects]
    outside = [t.get_text() for t, box in zip(objects, boxes)
               if box.x0 < -.5 or box.y0 < -.5 or box.x1 > fig.bbox.x1 + .5 or box.y1 > fig.bbox.y1 + .5]
    if outside:
        raise ValueError(f"Text outside the exact physical canvas: {outside}")
    text_overlaps = []
    for i, a in enumerate(boxes):
        for j, b in enumerate(boxes[i + 1:], i + 1):
            if min(a.x1, b.x1) - max(a.x0, b.x0) > 1 and min(a.y1, b.y1) - max(a.y0, b.y0) > 1:
                text_overlaps.append([objects[i].get_text(), objects[j].get_text()])
    if text_overlaps:
        raise ValueError(f"Overlapping text: {text_overlaps}")
    BASE.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png", "svg"):
        metadata = {"CreationDate": None, "ModDate": None} if ext == "pdf" else ({"Date": None} if ext == "svg" else None)
        fig.savefig(BASE.with_suffix("." + ext), dpi=600, metadata=metadata)
    command = shlex.join(["python", relative(Path(__file__)), *sys.argv[1:]])
    manifest = {
        "script": relative(Path(__file__)), "script_sha256": sha(Path(__file__)),
        "reproduce_working_directory": ".", "reproduce_command": command,
        "inputs": [{"path": relative(p), "sha256": sha(p)} for p in (SOURCE, CSV)],
        "runtime": {"python": platform.python_version(), "matplotlib": matplotlib.__version__},
        "layout": {"width_mm": WIDTH_MM, "height_mm": height / 72 * 25.4,
                   "minimum_font_pt": FONT_PT, "font_family": FAMILY, "png_dpi": 600,
                   "exact_page_size": True, "cropping": "none", "all_text_inside_canvas": True,
                   "text_overlap_count": 0},
        "source_example": example,
        "public_case_notice": "The original public GitHub account keys and usernames are retained for the illustrative case shown in the paper.",
        "displayed_panels": ["all-known", "human-only = post-filter"],
        "verification": {"post_filter_and_human_only_exactly_equal": True,
                         "all_csv_and_json_example_rows_match": True,
                         "all_ten_original_ranks_retained": True, "all_logins_unabridged": True,
                         "recommendations_recomputed": False, "scores_recomputed": False,
                         "target_flags_unchanged": True},
        "notes": "Only original candidate lists. Aggregate exposure/recall and rank-compression panels removed. Full post-filter and human-only lists share one column because row dictionaries are exactly equal. Line wrapping does not abbreviate logins.",
        "caption_suggestion": "Top-ten reviewer candidates in the public illustrative case. The observed human reviewer is marked with an asterisk.",
        "outputs": {ext: {"path": relative(BASE.with_suffix("." + ext)),
                          "sha256": sha(BASE.with_suffix("." + ext))} for ext in ("pdf", "png", "svg")}}
    BASE.with_name(BASE.name + "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BASE.with_name(BASE.name + "_reproduce_command.txt").write_text(command + "\n", encoding="utf-8")
    print(json.dumps({"width_mm": WIDTH_MM, "height_mm": height / 72 * 25.4,
                      "png": str(BASE.with_suffix(".png")), "text_overlaps": 0}))
    plt.close(fig)


if __name__ == "__main__":
    main()
