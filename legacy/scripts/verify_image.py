#!/usr/bin/env python3
import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path


def verify_imports(modules: list[str]) -> None:
    for module in modules:
        importlib.import_module(module)


def verify_paths(paths: list[str]) -> None:
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        raise FileNotFoundError("Missing expected path(s): " + ", ".join(missing))


def verify_nodes(names: list[str]) -> None:
    bases = [
        Path(os.environ.get("COMFYUI_DIR", "/opt/comfy/ComfyUI")) / "custom_nodes",
        Path(os.environ.get("BAKED_CUSTOM_NODES_DIR", "/opt/bootstrap/baked-custom-nodes")),
    ]
    missing = [name for name in names if not any((base / name).is_dir() for base in bases)]
    if missing:
        raise FileNotFoundError("Missing custom node(s): " + ", ".join(missing))


def verify_protected_manifest() -> None:
    manifest = Path("/opt/bootstrap/protected-package-manifest.json")
    if not manifest.is_file():
        return
    python = Path(os.environ.get("COMFY_VENV", "/opt/comfy/venv")) / "bin" / "python"
    subprocess.run(
        [
            str(python),
            "/opt/bootstrap/scripts/verify_protected_packages.py",
            "verify",
            str(manifest),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--import", dest="imports", action="append", default=[])
    parser.add_argument("--path", dest="paths", action="append", default=[])
    parser.add_argument("--node", dest="nodes", action="append", default=[])
    args = parser.parse_args()

    verify_paths(args.paths)
    verify_nodes(args.nodes)
    verify_imports(args.imports)
    verify_protected_manifest()
    print(f"{args.stage} image verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
