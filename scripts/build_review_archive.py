#!/usr/bin/env python3
"""Create a review ZIP from the checked publication manifest, without Git."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import zipfile
from verify_artifact import ROOT, privacy_checks, release_files, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT.parent / "msr2027-exp-review.zip")
    a = p.parse_args()
    if a.output.resolve().is_relative_to(ROOT):
        raise SystemExit("The review archive must be outside the publication directory.")
    files = release_files()
    assert not privacy_checks(files), "Publication hygiene check failed."
    manifest = ROOT / "MANIFEST.sha256"
    expected = dict((line.split("  ", 1)[1], line.split("  ", 1)[0])
                    for line in manifest.read_text().splitlines())
    actual = {p.relative_to(ROOT).as_posix() for p in files if p != manifest}
    assert actual == set(expected), "Publication manifest is stale."
    assert all(sha(ROOT / name) == digest for name, digest in expected.items())
    with zipfile.ZipFile(a.output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in files:
            z.write(path, "msr2027-exp/" + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(a.output) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist())) == len(files)
        assert not any("/outputs/" in name or "/.git/" in name for name in z.namelist())
    print(f"Review archive: {a.output.name}")
    print(f"Files: {len(files)}; ZIP bytes: {a.output.stat().st_size}")
    print(f"SHA256: {hashlib.sha256(a.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
