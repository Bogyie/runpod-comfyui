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
    "transformers",
]


def get_version(package_name: str):
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def collect(packages):
    return {name: get_version(name) for name in packages}


def write_constraints(manifest_path: Path, constraints_path: Path):
    """Emit a pip constraints file pinning every captured protected package.

    Passed to custom-node ``pip install`` via PIP_CONSTRAINT so a node's
    requirements can never silently upgrade/downgrade torch, transformers, etc.
    Packages absent from the environment are skipped.
    """
    captured = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = [
        f"{name}=={version}"
        for name, version in sorted(captured.items())
        if version is not None
    ]
    constraints_path.write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: verify_protected_packages.py "
            "<capture|verify|constraints> <manifest-path> "
            "[constraints-path|package ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]
    manifest_path = Path(sys.argv[2])

    if mode == "capture":
        packages = sys.argv[3:] or DEFAULT_PACKAGES
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

    if mode == "constraints":
        if len(sys.argv) < 4:
            print(
                "Usage: verify_protected_packages.py constraints "
                "<manifest-path> <constraints-path>",
                file=sys.stderr,
            )
            sys.exit(1)
        write_constraints(manifest_path, Path(sys.argv[3]))
        return

    print(f"Unsupported mode: {mode}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
