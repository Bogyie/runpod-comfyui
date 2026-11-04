#!/usr/bin/env python3
"""Generate reproducible static compatibility evidence from verified source snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def inspect_source(root: Path, entry: dict) -> dict:
    for name, expected in entry["files"].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Source changed after snapshot: {entry['repository']}/{name}")
    project = tomllib.loads((root / "pyproject.toml").read_text()) if (root / "pyproject.toml").is_file() else {}
    metadata = project.get("project", {})
    root_config = root / "comfy-env-root.toml"
    cfg = tomllib.loads(root_config.read_text()) if root_config.is_file() else {}
    workers = {}
    for name in sorted(entry["files"]):
        if Path(name).name == "comfy-env.toml":
            workers[name] = tomllib.loads((root / name).read_text())
    init = root / "__init__.py"
    text = init.read_text() if init.is_file() else ""
    native = bool(workers) and "register_nodes" in text and "comfy_env" in text
    return {
        "commit": entry["commit"], "repository": entry["repository"], "role": entry["role"],
        "version": metadata.get("version"), "requires_python": metadata.get("requires-python"),
        "project_dependencies": metadata.get("dependencies", []),
        "requirements": (root / "requirements.txt").read_text().splitlines() if (root / "requirements.txt").is_file() else [],
        "install_hooks": [n for n in ("install.py", "prestartup_script.py") if (root / n).is_file()],
        "node_dependencies": cfg.get("node_reqs", cfg.get("node_packs", {})),
        "worker_configs": workers,
        "isolation_evidence": "upstream-configured-not-execution-verified" if native else "adapter-investigation-required",
        "execution_verified": False,
    }


def audit(lock: dict, cache: Path) -> dict:
    sources = {name: inspect_source(cache / name / entry["commit"], entry)
               for name, entry in lock["sources"].items()}
    known = {s["repository"].lower() for s in sources.values()}
    missing = sorted({repo for s in sources.values() for repo in s["node_dependencies"].values()
                      if isinstance(repo, str) and repo.lower() not in known})
    return {"schema_version": 1, "kind": "static-source-audit", "gpu_verified": False,
            "missing_node_sources": missing, "sources": sources}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "locks/upstreams.lock.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".work/upstreams")
    parser.add_argument("--output", type=Path, default=ROOT / "build/upstream-audit.json")
    args = parser.parse_args()
    result = audit(json.loads(args.lock.read_text()), args.cache)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if result["missing_node_sources"]:
        raise SystemExit("Unpinned transitive nodes: " + ", ".join(result["missing_node_sources"]))
    print(f"Audited {len(result['sources'])} pinned sources; GPU execution remains unverified")


if __name__ == "__main__":
    main()
