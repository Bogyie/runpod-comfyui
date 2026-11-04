#!/usr/bin/env python3
"""Build an experimental Linux host probe locally; publication is handled by CI.

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
    parser.add_argument("--target", choices=["gpu-base", "host", "worker-probe"])
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    stack = yaml.safe_load((ROOT / "build/stack.yaml").read_text())
    args.target = args.target or stack.get("candidate", {}).get("target", "host")
    lock = json.loads((ROOT / "locks/upstreams.lock.json").read_text())
    context = ROOT / ".work/probe-context"
    context.mkdir(parents=True, exist_ok=True)
    for name in ("gpu", "host"):
        shutil.copyfile(ROOT / f"locks/{name}/linux-amd64-cu128.txt", context / f"{name}.txt")
    shutil.copyfile(ROOT / "tools/rebuild/apply_comfy_env_patch.py", context / "apply_comfy_env_patch.py")
    if args.target in {"host", "worker-probe"}:
        source = lock["sources"]["comfyui"]
        data = fetch(source["archive_url"])
        if digest(data) != source["archive_sha256"]:
            raise ValueError("ComfyUI source archive hash mismatch")
        destination = context / "ComfyUI"
        if destination.exists():
            shutil.rmtree(destination)
        materialize(data, destination)
    if args.target == "worker-probe":
        import concurrent.futures
        definitions = json.loads((ROOT / "locks/workers/manifest.json").read_text())
        if definitions.get('gpu_lock_sha256') != digest((ROOT/'locks/gpu/linux-amd64-cu128.txt').read_bytes()):
            raise ValueError('Worker GPU lock identity changed without re-locking')
        inputs = json.loads((ROOT / "build/inputs/workers/workers.json").read_text())
        worker_locks = context / "worker-locks"
        worker_locks.mkdir(exist_ok=True)
        for name, definition in definitions['workers'].items():
            recorded = {key:value for key,value in definition.items() if key not in {'lock_file','lock_sha256'}}
            if recorded != inputs['workers'][name]:
                raise ValueError(f'Worker definition changed without re-locking: {name}')
            for field in ['lock_file','environment','plugin_directory']:
                value = definition[field]
                if not value or Path(value).name != value or value in {'.','..'}:
                    raise ValueError(f'Unsafe worker {field}: {value}')
            if definition['commit'] != lock['sources'][definition['source']]['commit']:
                raise ValueError(f'Worker source changed without re-locking: {name}')
            if definition.get('adapter'):
                from prepare_workers import adapter_identity
                if adapter_identity(definition['adapter']) != definition.get('adapter_files_sha256'):
                    raise ValueError('Worker adapter changed without re-locking')
            raw_lock = (ROOT / 'locks/workers' / definition['lock_file']).read_bytes()
            if digest(raw_lock) != definition['lock_sha256']:
                raise ValueError(f'Worker lock file changed: {name}')
            (worker_locks / definition['lock_file']).write_bytes(raw_lock)
        (worker_locks/'manifest.json').write_text(json.dumps(definitions,indent=2,sort_keys=True)+'\n')
        for script in ['link_gpu_packages.py','install_worker_envs.py']:
            shutil.copyfile(ROOT/'tools/rebuild'/script,context/script)
        nodes_root = context / 'worker-nodes'
        if nodes_root.exists():
            shutil.rmtree(nodes_root)
        def prepare_node(definition):
            source = lock['sources'][definition['source']]
            data = fetch(source['archive_url'])
            if digest(data) != source['archive_sha256']:
                raise ValueError(f"Node source archive hash mismatch: {definition['source']}")
            materialize(data,nodes_root/definition['plugin_directory'])
            if definition.get('adapter'):
                if definition['adapter'] == 'itools':
                    from apply_itools_adapter import apply
                elif definition['adapter'] == 'kjnodes':
                    from apply_kjnodes_adapter import apply
                else:
                    raise ValueError('Unknown worker source adapter')
                apply(nodes_root/definition['plugin_directory'],source,ROOT/'build/adapters'/definition['adapter'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(prepare_node,definitions['workers'].values()))
    if args.prepare_only:
        print(context)
        return
    command = ["docker", "buildx", "build", "--load", "--platform", stack["platform"],
               "--file", str(ROOT / "docker/Dockerfile.probe"), "--target", args.target,
               "--tag", f"runpod-comfyui:probe-{args.target}", "--progress", "plain",
               "--build-arg", f"BASE_IMAGE={stack['base_image']}",
               "--build-arg", f"UV_VERSION={stack['resolver']['uv']}",
               "--build-arg", f"TORCH_BACKEND={stack['gpu']['torch_backend']}",
               "--build-arg", f"WORKER_ATTENTION={stack['gpu']['attention_default']}", str(context)]
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
