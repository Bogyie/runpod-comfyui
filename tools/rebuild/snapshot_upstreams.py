#!/usr/bin/env python3
"""Resolve upstreams explicitly, or reproduce pinned audit snapshots without executing them.

The discovery input is not a production dependency lock. Production builds must use
the resolved lock, never latest-release or a moving branch. Requires Python 3.11+.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
LIMIT = 128 * 1024 * 1024


def fetch(url: str) -> bytes:
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "runpod-comfyui-audit/1"})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise ValueError(f"Upstream response exceeds {LIMIT} bytes")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_archive(data: bytes, destination: Path | None = None) -> dict:
    """Read regular text/source files only; never extract links or execute install hooks."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] == "/" or ".." in parts:
                raise ValueError(f"Unsafe archive member: {member.name}")
            if not member.isfile() or len(parts) < 2:
                continue
            relative = PurePosixPath(*parts[1:])
            if relative.suffix not in {".py", ".toml", ".txt", ".json", ".md", ".yaml", ".yml"}:
                continue
            if member.size > 4 * 1024 * 1024:
                continue
            stream = archive.extractfile(member)
            assert stream is not None
            content = stream.read()
            files[str(relative)] = digest(content)
            if destination is not None:
                target = destination / relative
                # Cache is local, but do not follow preexisting symlink directories.
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError(f"Snapshot path escapes cache: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink():
                    raise ValueError(f"Refusing cache symlink: {target}")
                target.write_bytes(content)
    return dict(sorted(files.items()))


def resolve(name: str, source: dict, cache: Path) -> tuple[str, dict]:
    repo = source["repository"]
    if not REPOSITORY.fullmatch(repo):
        raise ValueError(f"Invalid repository: {repo}")
    ref = source["ref"]
    if ref == "default-branch":
        ref = json.loads(fetch(f"https://api.github.com/repos/{repo}"))["default_branch"]
    if ref == "latest-release":
        release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))
        ref = release["tag_name"]
    commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/{urllib.parse.quote(ref, safe='')}"))
    sha = commit["sha"]
    if not SHA.fullmatch(sha):
        raise ValueError(f"Invalid upstream SHA: {sha}")
    url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
    data = fetch(url)
    entry = {
        "repository": repo, "role": source["role"], "resolved_ref": ref,
        "commit": sha, "archive_url": url, "archive_sha256": digest(data),
        "files": inspect_archive(data, cache / name / sha),
    }
    print(f"Pinned {name}: {sha}", flush=True)
    return name, entry


def reproduce(name: str, entry: dict, cache: Path) -> None:
    repo, sha = entry["repository"], entry["commit"]
    if not REPOSITORY.fullmatch(repo) or not SHA.fullmatch(sha):
        raise ValueError(f"Invalid locked repository/commit: {name}")
    # Construct the URL from validated identity; ignore arbitrary URL overrides.
    data = fetch(f"https://codeload.github.com/{repo}/tar.gz/{sha}")
    if digest(data) != entry["archive_sha256"]:
        raise ValueError(f"Archive hash mismatch: {name}")
    files = inspect_archive(data)
    if files != entry["files"]:
        raise ValueError(f"Source manifest mismatch: {name}")
    inspect_archive(data, cache / name / sha)
    print(f"Verified {name}: {sha}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", action="store_true", help="Explicitly refresh upstream pins (network)")
    parser.add_argument("--input", type=Path, default=ROOT / "build/upstreams.json")
    parser.add_argument("--lock", type=Path, default=ROOT / "locks/upstreams.lock.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".work/upstreams")
    args = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        if args.resolve:
            spec = json.loads(args.input.read_text())
            futures = [pool.submit(resolve, name, src, args.cache) for name, src in spec["sources"].items()]
            sources = dict(f.result() for f in futures)
            result = {"schema_version": 1, "kind": "source-audit-lock", "sources": dict(sorted(sources.items()))}
            args.lock.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.lock.with_suffix(".tmp")
            temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            temporary.replace(args.lock)
        else:
            lock = json.loads(args.lock.read_text())
            futures = [pool.submit(reproduce, name, entry, args.cache) for name, entry in lock["sources"].items()]
            for future in futures:
                future.result()


if __name__ == "__main__":
    main()
