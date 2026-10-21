#!/usr/bin/env python3
"""Verify release checksums, input invariants, and publication hygiene.

No network requests are made. Findings identify files/categories without
printing potentially sensitive matching values. Generated outputs are local
work products and are excluded from the publication file set.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", "outputs", ".venv", ".pytest_cache", "__pycache__", "private"}
EXCLUDED_SUFFIXES = {".pyc", ".log", ".tmp"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".csv", ".yml", ".yaml", ".toml", ".sh"}


def release_files(root=ROOT):
    return sorted(p for p in root.rglob("*") if p.is_file()
                  and not any(x in EXCLUDED_PARTS or x.startswith(".venv") for x in p.relative_to(root).parts)
                  and p.name != ".DS_Store" and p.suffix not in EXCLUDED_SUFFIXES)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def privacy_checks(files):
    # Build sensitive patterns from components so the scanner's own source
    # does not look like a real credential or a recorded machine location.
    patterns = {
        "github_token": re.compile(r"gh[pousr]_" + r"[A-Za-z0-9]{20,}|github_pat_" + r"[A-Za-z0-9_]{25,}"),
        "model_token": re.compile(r"\b(?:sk|hf)-?" + r"[A-Za-z0-9_]{28,}\b"),
        "private_key": re.compile("BEGIN " + r"(?:RSA |OPENSSH |EC )?PRIVATE KEY"),
        "bearer_credential": re.compile("Bearer " + r"[A-Za-z0-9_.~+/=-]{20,}"),
        "machine_home_path": re.compile(r"/(?:Users|home)/" + r"[^\s/\"'<>]+/"),
        "private_ipv4": re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
        "email": re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_.+-]+@" + r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    }
    findings = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or path.name in {".env", "config.yaml", "config.yml", "alias_maps.json"}:
            findings.append({"file": rel, "category": "forbidden_file"})
        if path.suffix in TEXT_SUFFIXES or path.name == ".gitignore":
            text = path.read_text(encoding="utf-8")
            for category, pattern in patterns.items():
                if pattern.search(text):
                    findings.append({"file": rel, "category": category})
    return findings


def data_checks():
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    events = ROOT / "data/processed/actor_pr_events.parquet"
    labels = ROOT / "data/processed/actor_labels.parquet"
    event_file, label_file = pq.ParquetFile(events), pq.ParquetFile(labels)
    assert event_file.metadata.num_rows == 4222224
    assert label_file.metadata.num_rows == 425548
    table = pq.read_table(events, columns=["source_node", "repo_url", "target_node", "pr_id", "repo_id"])
    sources = pc.unique(table["source_node"]).to_pylist()
    tools = {"agent:" + x for x in ["Claude_Code", "Copilot", "Cursor", "Devin", "Google_Jules", "OpenAI_Codex"]}
    original_account = re.compile(r"actor:(?:id:|login:).+")
    assert all(original_account.fullmatch(x) or x in tools for x in sources)
    repo_urls = pc.unique(table["repo_url"]).to_pylist()
    assert any(repo_urls), "Original public repository URLs must be retained."
    assert all(x in {None, ""} or x.startswith(("https://api.github.com/", "https://github.com/")) for x in repo_urls)
    assert len(sources) == 45598
    assert len(pc.unique(table["pr_id"])) == 361296
    assert len(pc.unique(table["repo_id"])) == 25402
    assert any(pc.unique(pq.read_table(labels, columns=["login"])["login"]).to_pylist())
    assert all(x.startswith(("id:", "login:")) for x in pc.unique(pq.read_table(labels, columns=["actor_key"])["actor_key"]).to_pylist())
    return {"event_rows": 4222224, "account_label_rows": 425548,
            "observed_account_nodes": 45598, "prs": 361296, "repositories": 25402,
            "original_public_logins_and_repo_urls_retained": True,
            "original_account_identifiers_retained": True,
            "identifier_anonymization_applied": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--make-manifest", action="store_true")
    p.add_argument("--skip-data", action="store_true")
    a = p.parse_args()
    files = release_files()
    findings = privacy_checks(files)
    if findings:
        print(json.dumps({"privacy_scan_passed": False, "findings": findings}, indent=2))
        raise SystemExit(1)
    manifest = ROOT / "MANIFEST.sha256"
    if a.make_manifest:
        manifest.write_text("".join(f"{sha(f)}  {f.relative_to(ROOT).as_posix()}\n"
                                    for f in files if f != manifest))
    if not manifest.exists():
        raise SystemExit("No MANIFEST.sha256. Prepare it with --make-manifest before distributing.")
    expected = {}
    for line in manifest.read_text().splitlines():
        digest, relative = line.split("  ", 1); expected[relative] = digest
    actual_names = {x.relative_to(ROOT).as_posix() for x in release_files() if x != manifest}
    assert actual_names == set(expected), "Publication file list differs from the manifest."
    failures = [name for name, digest in expected.items() if sha(ROOT / name) != digest]
    assert not failures, f"Checksum mismatch in {len(failures)} files."
    results = {} if a.skip_data else data_checks()
    print(json.dumps({"manifest_files": len(expected), "checksums_passed": True,
                      "privacy_scan_passed": True, "privacy_findings": 0,
                      "published_bytes": sum((ROOT / name).stat().st_size for name in expected),
                      "data": results}, indent=2))


if __name__ == "__main__":
    main()
