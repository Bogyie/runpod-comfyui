#!/usr/bin/env python3
"""Inspect the exact locked comfy-env wheel without importing or installing it."""
from __future__ import annotations

import argparse
import io
import json
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath

from snapshot_upstreams import ROOT, digest, fetch


def extract(data: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe wheel path")
            if not name.startswith("comfy_env/") or not name.endswith(".py"):
                continue
            target = destination / path
            if not target.resolve().is_relative_to(destination.resolve()) or target.is_symlink():
                raise ValueError("Wheel target escapes snapshot directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "locks/comfy-env-artifact.json")
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    url = urllib.parse.urlsplit(lock["url"])
    if url.scheme != "https" or url.hostname != "files.pythonhosted.org" or url.username:
        raise ValueError("Unexpected locked artifact URL")
    data = fetch(lock["url"])
    if digest(data) != lock["sha256"]:
        raise ValueError("Wheel hash mismatch")
    extract(data, ROOT / ".work" / f"comfy-env-{lock['version']}")
    print(f"Verified comfy-env {lock['version']} wheel; no code executed")


if __name__ == "__main__":
    main()
