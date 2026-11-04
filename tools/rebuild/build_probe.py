#!/usr/bin/env python3
"""Build an experimental Linux host probe; never publish or promote it.

Uses complete archive contents, not the text-only audit snapshot. Model/GPU and
custom-node execution are separate gates after this core startup probe.
"""
from __future__ import annotations

import argparse
import io
import json
import platform
import shutil
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath

import yaml

from snapshot_upstreams import ROOT, digest, fetch


def materialize(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for item in archive:
            parts = PurePosixPath(item.name).parts
            if not parts or parts[0] == "/" or ".." in parts:
                raise ValueError("Unsafe source archive path")
            if item.isdir():
                continue
            if not item.isfile():
                raise ValueError(f"Nonregular source archive entry: {item.name}")
            if len(parts) < 2:
                raise ValueError("Missing archive root")
            target = destination.joinpath(*parts[1:])
            if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Source extraction target escapes destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["gpu-base", "host"], default="host")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    stack = yaml.safe_load((ROOT / "build/stack.yaml").read_text())
    lock = json.loads((ROOT / "locks/upstreams.lock.json").read_text())
    context = ROOT / ".work/probe-context"
    context.mkdir(parents=True, exist_ok=True)
    for name in ("gpu", "host"):
        shutil.copyfile(ROOT / f"locks/{name}/linux-amd64-cu128.txt", context / f"{name}.txt")
    shutil.copyfile(ROOT / "tools/rebuild/apply_comfy_env_patch.py", context / "apply_comfy_env_patch.py")
    if args.target == "host":
        source = lock["sources"]["comfyui"]
        data = fetch(source["archive_url"])
        if digest(data) != source["archive_sha256"]:
            raise ValueError("ComfyUI source archive hash mismatch")
        destination = context / "ComfyUI"
        if destination.exists():
            shutil.rmtree(destination)
        materialize(data, destination)
    if args.prepare_only:
        print(context)
        return
    command = ["docker", "buildx", "build", "--load", "--platform", stack["platform"],
               "--file", str(ROOT / "docker/Dockerfile.probe"), "--target", args.target,
               "--tag", f"runpod-comfyui:probe-{args.target}", "--progress", "plain",
               "--build-arg", f"BASE_IMAGE={stack['base_image']}",
               "--build-arg", f"UV_VERSION={stack['resolver']['uv']}",
               "--build-arg", f"TORCH_BACKEND={stack['gpu']['torch_backend']}", str(context)]
    started = time.monotonic()
    with (ROOT / ".work/probe-build.log").open("w") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        result = process.wait()
    if result:
        raise subprocess.CalledProcessError(result, command)
    identity = {
        "kind": "local-experimental-build", "target": args.target,
        "host": {"system": platform.system(), "architecture": platform.machine()},
        "image_platform": stack["platform"], "base_image": stack["base_image"],
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "lock_hashes": {name: digest((context / f"{name}.txt").read_bytes()) for name in ["gpu", "host"]},
        "scope": "Local Docker build only; not a GitHub Actions benchmark or GPU validation",
    }
    evidence = ROOT / "tests/evidence" / f"build-probe-{args.target}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
