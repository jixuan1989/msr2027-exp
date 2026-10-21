#!/usr/bin/env python3
"""Resumable, parallel downloader for the AIDev Hugging Face dataset.

The script is intentionally dependency-light (Python standard library only).
It downloads files to ``*.part`` and atomically renames completed files, so a
process can be interrupted and resumed safely. A compact JSON manifest and a
human-readable progress log are written beside the data.

Examples
--------
    python scripts/download_aidev.py \
        --out-dir /data/aidev-7.6m \
        --endpoint https://hf-mirror.com \
        --workers 3

    # Download only the tables needed for the first schema/label pass:
    python scripts/download_aidev.py --only \
        all_pull_request.parquet all_user.parquet all_repository.parquet \
        pr_comments.parquet pr_reviews.parquet pr_review_comments.parquet \
        pr_commits.parquet pr_commit_details.parquet pr_timeline.parquet \
        --out-dir /data/aidev-7.6m --workers 3
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPO = "hao-li/AIDev-7.6M"
DEFAULT_REVISION = "main"
DEFAULT_ENDPOINT = "https://hf-mirror.com"


def http_json(url: str, retries: int = 6) -> object:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "aidev-repro-downloader/1.0"})
            with urlopen(req, timeout=60) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def fetch_manifest(endpoint: str, repo: str, revision: str) -> list[dict]:
    api = f"{endpoint.rstrip('/')}/api/datasets/{repo}/tree/{revision}?recursive=true&expand=false"
    listing = http_json(api)
    if not isinstance(listing, list):
        raise RuntimeError(f"unexpected API response from {api}")
    files = []
    for item in listing:
        if item.get("type") != "file":
            continue
        path = item.get("path", "")
        if not path.endswith(".parquet"):
            continue
        files.append(
            {
                "path": path,
                "size": int(item.get("size") or 0),
                "oid": item.get("oid"),
                "lfs": item.get("lfs") or {},
            }
        )
    files.sort(key=lambda x: x["path"])
    return files


class Progress:
    def __init__(self, files: list[dict], out_dir: Path, log_path: Path):
        self.out_dir = out_dir
        self.log_path = log_path
        self.lock = threading.Lock()
        self.last_report = 0.0
        self.state = {
            f["path"]: {
                "size": f["size"],
                "done": 0,
                "status": "pending",
                "started": None,
                "finished": None,
                "error": None,
            }
            for f in files
        }

    def update(self, path: str, **kwargs) -> None:
        with self.lock:
            self.state[path].update(kwargs)

    def add_done(self, path: str, n: int) -> None:
        with self.lock:
            self.state[path]["done"] += n

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state))

    def report(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_report < 5:
            return
        self.last_report = now
        s = self.snapshot()
        total = sum(x["size"] for x in s.values())
        done = sum(min(x["done"], x["size"]) for x in s.values())
        active = sum(x["status"] == "downloading" for x in s.values())
        complete = sum(x["status"] == "complete" for x in s.values())
        pct = (100 * done / total) if total else 100.0
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"overall={pct:6.2f}% ({done/1e9:.2f}/{total/1e9:.2f} GB) "
            f"complete={complete}/{len(s)} active={active}"
        )
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def download_one(
    entry: dict,
    endpoint: str,
    repo: str,
    revision: str,
    out_dir: Path,
    progress: Progress,
    chunk_size: int = 8 * 1024 * 1024,
    segments: int = 4,
    segment_threshold: int = 256 * 1024 * 1024,
) -> str:
    rel = Path(entry["path"])
    dest = out_dir / rel
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = int(entry["size"])

    if dest.exists() and dest.stat().st_size == expected:
        progress.update(str(rel), done=expected, status="complete", finished=time.time())
        return str(rel)
    if dest.exists() and dest.stat().st_size != expected:
        dest.unlink()
    url = f"{endpoint.rstrip('/')}/datasets/{repo}/resolve/{revision}/{entry['path']}?download=true"

    # Large LFS objects are split into HTTP byte ranges. This uses several
    # connections per file and is substantially faster on mirrors that throttle
    # a single stream. Each range is resumable and is merged atomically.
    if expected >= segment_threshold and segments > 1:
        ranges = []
        for idx in range(segments):
            start = expected * idx // segments
            end = expected * (idx + 1) // segments - 1
            ranges.append((idx, start, end))
        segment_paths = [dest.with_name(dest.name + f".part.{idx:03d}") for idx, _, _ in ranges]
        initial_done = 0
        for path, (_, start, end) in zip(segment_paths, ranges):
            segment_len = end - start + 1
            if path.exists() and path.stat().st_size > segment_len:
                path.unlink()
            initial_done += min(path.stat().st_size if path.exists() else 0, segment_len)
        progress.update(str(rel), done=initial_done, status="downloading", started=time.time())

        def fetch_segment(item: tuple[int, int, int]) -> None:
            idx, start, end = item
            segment_len = end - start + 1
            seg = dest.with_name(dest.name + f".part.{idx:03d}")
            current = seg.stat().st_size if seg.exists() else 0
            for attempt in range(8):
                try:
                    if current > segment_len:
                        seg.unlink()
                        current = 0
                    request = Request(
                        url,
                        headers={
                            "User-Agent": "aidev-repro-downloader/1.0",
                            "Range": f"bytes={start + current}-{end}",
                        },
                    )
                    with urlopen(request, timeout=120) as response:
                        status = getattr(response, "status", 200)
                        if status != 206:
                            raise IOError(f"range request returned HTTP {status}")
                        with seg.open("ab" if current else "wb") as fh:
                            while True:
                                block = response.read(chunk_size)
                                if not block:
                                    break
                                fh.write(block)
                                current += len(block)
                                progress.add_done(str(rel), len(block))
                    if current != segment_len:
                        raise IOError(f"segment {idx} size mismatch: got {current}, expected {segment_len}")
                    return
                except Exception as exc:
                    progress.update(str(rel), error=f"segment {idx}, attempt {attempt+1}: {exc}")
                    if attempt == 7:
                        raise
                    time.sleep(min(2**attempt, 60))
                    current = seg.stat().st_size if seg.exists() else 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=segments) as segment_pool:
            list(segment_pool.map(fetch_segment, ranges))
        part = dest.with_name(dest.name + ".part")
        with part.open("wb") as out:
            for path in segment_paths:
                with path.open("rb") as inp:
                    shutil.copyfileobj(inp, out, length=chunk_size)
        if part.stat().st_size != expected:
            raise IOError(f"merged file size mismatch: got {part.stat().st_size}, expected {expected}")
        os.replace(part, dest)
        for path in segment_paths:
            path.unlink(missing_ok=True)
        progress.update(str(rel), done=expected, status="complete", finished=time.time())
        return str(rel)

    current = part.stat().st_size if part.exists() else 0
    progress.update(str(rel), done=current, status="downloading", started=time.time())

    for attempt in range(8):
        try:
            headers = {"User-Agent": "aidev-repro-downloader/1.0"}
            if current:
                headers["Range"] = f"bytes={current}-"
            request = Request(url, headers=headers)
            with urlopen(request, timeout=120) as response:
                # A server that ignores Range returns the whole object. In that
                # case restart the .part file rather than corrupting it.
                status = getattr(response, "status", 200)
                if current and status != 206:
                    current = 0
                    part.unlink(missing_ok=True)
                mode = "ab" if current else "wb"
                with part.open(mode) as fh:
                    while True:
                        block = response.read(chunk_size)
                        if not block:
                            break
                        fh.write(block)
                        current += len(block)
                        progress.add_done(str(rel), len(block))
            if current != expected:
                raise IOError(f"size mismatch: got {current}, expected {expected}")
            os.replace(part, dest)
            progress.update(str(rel), done=expected, status="complete", finished=time.time())
            return str(rel)
        except Exception as exc:  # retry network interruptions and partial files
            progress.update(str(rel), error=f"attempt {attempt+1}: {exc}")
            if attempt == 7:
                progress.update(str(rel), status="failed", finished=time.time())
                raise
            time.sleep(min(2**attempt, 60))
            current = part.stat().st_size if part.exists() else 0
            progress.update(str(rel), done=current)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--segments", type=int, default=4, help="HTTP ranges per large file")
    parser.add_argument("--segment-threshold-mb", type=int, default=256)
    parser.add_argument("--only", nargs="*", default=None, help="optional parquet file names")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    if args.segments < 1 or args.segments > 8:
        parser.error("--segments must be between 1 and 8")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = fetch_manifest(args.endpoint, args.repo, args.revision)
    if args.only:
        wanted = set(args.only)
        manifest = [x for x in manifest if x["path"] in wanted or Path(x["path"]).name in wanted]
        missing = wanted - {x["path"] for x in manifest} - {Path(x["path"]).name for x in manifest}
        if missing:
            parser.error(f"unknown parquet files: {sorted(missing)}")
    if not manifest:
        parser.error("manifest has no files")

    metadata = {
        "repo": args.repo,
        "revision": args.revision,
        "endpoint": args.endpoint,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": manifest,
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    log_path = args.out_dir / "download.log"
    progress = Progress(manifest, args.out_dir, log_path)
    progress.report(force=True)

    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {
            pool.submit(
                download_one,
                f,
                args.endpoint,
                args.repo,
                args.revision,
                args.out_dir,
                progress,
                segments=args.segments,
                segment_threshold=args.segment_threshold_mb * 1024 * 1024,
            ): f["path"]
            for f in manifest
        }
        while jobs:
            done, _ = concurrent.futures.wait(jobs, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED)
            progress.report()
            for future in done:
                path = jobs.pop(future)
                try:
                    future.result()
                    print(f"finished {path}", flush=True)
                except Exception as exc:
                    failures.append(path)
                    print(f"FAILED {path}: {exc}", file=sys.stderr, flush=True)
        progress.report(force=True)

    (args.out_dir / "download_state.json").write_text(
        json.dumps(progress.snapshot(), indent=2), encoding="utf-8"
    )
    if failures:
        print(f"{len(failures)} file(s) failed; rerun the same command to resume", file=sys.stderr)
        return 2
    print("download complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
