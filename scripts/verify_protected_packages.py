#!/usr/bin/env python3
import json
import sys
from importlib import metadata
from pathlib import Path


DEFAULT_PACKAGES = [
    "torch",
    "torchvision",
    "torchaudio",
    "xformers",
    "triton",
    "sageattention",
]


def get_version(package_name: str):
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def collect(packages):
    return {name: get_version(name) for name in packages}


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: verify_protected_packages.py <capture|verify> <manifest-path> [package ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]
    manifest_path = Path(sys.argv[2])
    packages = sys.argv[3:] or DEFAULT_PACKAGES

    if mode == "capture":
        manifest_path.write_text(
            json.dumps(collect(packages), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return

    if mode == "verify":
        expected = json.loads(manifest_path.read_text(encoding="utf-8"))
        current = collect(expected.keys())
        if current != expected:
            print("Protected package drift detected.", file=sys.stderr)
            print("Expected:", json.dumps(expected, indent=2, sort_keys=True), file=sys.stderr)
            print("Current:", json.dumps(current, indent=2, sort_keys=True), file=sys.stderr)
            sys.exit(1)
        return

    print(f"Unsupported mode: {mode}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
