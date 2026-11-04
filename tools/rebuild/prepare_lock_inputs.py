#!/usr/bin/env python3
"""Generate candidate lock inputs from verified source pins and one stack manifest.

This does not resolve/install dependencies and does not certify GPU compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from audit_upstreams import audit
from snapshot_upstreams import ROOT


def prepare(stack: dict, source_lock: dict, cache: Path, output: Path) -> None:
    inspected = audit(source_lock, cache)
    if inspected["missing_node_sources"]:
        raise ValueError("Transitive node sources must be pinned first")
    output.mkdir(parents=True, exist_ok=True)
    gpu = stack["gpu"]
    packages = ("torch", "torchvision", "torchaudio", "xformers")
    gpu_requirements = "".join(f"{name}=={gpu[name]}\n" for name in packages)
    (output / "gpu.in").write_text(gpu_requirements)
    lines = ["# Generated from pinned upstream source files; edit build/stack.yaml instead."]
    for name in stack["host_requirements_sources"]:
        source = inspected["sources"][name]
        lines.append(f"\n# {source['repository']}@{source['commit']}")
        lines.extend(source["requirements"])
    for name, exception in stack.get('host_extra_requirements', {}).items():
        source=inspected['sources'][exception['source']]
        requirement=exception['requirement']
        if requirement not in source['requirements']:
            raise ValueError('Unreviewed host exception requirement: '+name)
        lines.extend([f"\n# Host exception: {exception['reason']}; {source['repository']}@{source['commit']}",requirement])
    lines.extend(["\n# Pin the installer used by Manager/comfy-env as well as by CI",
                  f"uv=={stack['resolver']['uv']}",
                  "\n# GPU stack may not drift during application resolution", gpu_requirements.strip()])
    (output / "host.in").write_text("\n".join(lines) + "\n")
    identity = {"stack": stack, "sources": {name: item["commit"] for name, item in source_lock["sources"].items()}}
    (output / "identity.json").write_text(json.dumps({
        "kind": "candidate-input-identity", "gpu_verified": False,
        "sha256": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
        "inputs": identity,
    }, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", type=Path, default=ROOT / "build/stack.yaml")
    parser.add_argument("--sources", type=Path, default=ROOT / "locks/upstreams.lock.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".work/upstreams")
    parser.add_argument("--output", type=Path, default=ROOT / "build/inputs")
    args = parser.parse_args()
    prepare(yaml.safe_load(args.stack.read_text()), json.loads(args.sources.read_text()), args.cache, args.output)
    print("Prepared experimental GPU/host requirements; GPU compatibility not yet certified")


if __name__ == "__main__":
    main()
