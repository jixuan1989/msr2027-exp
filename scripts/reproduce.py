#!/usr/bin/env python3
"""Run the final experiments from the supplied selected AIDev snapshot."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["verify", "graph", "rq1", "rq2", "rq3", "figures", "check", "all"], default="verify")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    out = args.output_dir
    if not out.is_absolute():
        out = ROOT / out

    def run(script, *arguments):
        command = [sys.executable, str(ROOT / "scripts" / script), *map(str, arguments)]
        print(f"Running {script}", flush=True)
        subprocess.run(command, cwd=ROOT, check=True)

    stages = ["verify", "graph", "rq1", "rq2", "rq3", "check", "figures"] if args.stage == "all" else [args.stage]
    for stage in stages:
        if stage == "verify":
            run("verify_artifact.py")
        elif stage == "graph":
            run("build_role_aware_network.py", "--events", "data/processed/actor_pr_events.parquet",
                "--actor-labels", "data/processed/actor_labels.parquet", "--out", out / "role_aware_network")
        elif stage == "rq1":
            run("run_rq1.py", "--role-edges", out / "role_aware_network/edges.parquet", "--out-dir", out / "rq1")
        elif stage in {"rq2", "rq3"}:
            run(f"run_{stage}.py", "--out-dir", out / stage)
        elif stage == "check":
            run("check_results.py", "--result-dir", out)
        elif stage == "figures":
            run("render_figures.py", "--out-dir", out / "figures")


if __name__ == "__main__":
    main()
