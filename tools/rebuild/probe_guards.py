#!/usr/bin/env python3
"""Verify guards in the installed Linux image, including actual node registration."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = r'''
import importlib.util, json, os, pathlib, sys
from comfy_env.install.workspace import _resolve_workspace_torch
os.environ['COMFYCTL_BUILD_CUDA'] = '12.8'
combo = _resolve_workspace_torch(lambda message: None)
assert combo == ('https://download.pytorch.org/whl/cu128', '12.8', '12', '3.11', '2.10.0'), combo
os.environ['COMFYCTL_BUILD_CUDA'] = '13.0'
try:
    _resolve_workspace_torch(lambda message: None)
except RuntimeError as exc:
    assert 'must match' in str(exc), str(exc)
else:
    raise AssertionError('Mismatched CUDA target was accepted')
del os.environ['COMFYCTL_BUILD_CUDA']
os.environ['COMFYCTL_REQUIRE_ISOLATION'] = '1'
os.environ['COMFY_ENV_ROOT'] = '/tmp/isolated-guard-workspace'
root = pathlib.Path('/opt/probe/ComfyUI/custom_nodes/GuardProbe')
(root / 'nodes').mkdir(parents=True)
(root / 'nodes/comfy-env.toml').write_text('[pypi-dependencies]\nnumpy="*"\n'.replace('\\n', '\n'))
(root / 'nodes/__init__.py').write_text("raise AssertionError('Host import must never execute')\n".replace('\\n', '\n'))
(root / '__init__.py').write_text('from comfy_env import register_nodes\nNODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = register_nodes()\n'.replace('\\n', '\n'))
spec = importlib.util.spec_from_file_location('guardprobe', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec)
sys.modules['guardprobe'] = module
try:
    spec.loader.exec_module(module)
except RuntimeError as exc:
    assert 'Required isolation environment is missing' in str(exc), str(exc)
else:
    raise AssertionError('Missing environment reached in-process import')
print(json.dumps({'kind':'installed-comfy-env-guard-gate','explicit_cuda_target':'passed',
    'mismatched_cuda_target':'rejected','missing_worker_host_fallback':'rejected',
    'scope':'Installed build/registration guards only; no worker execution or GPU certification'}))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="runpod-comfyui:probe-host")
    parser.add_argument("--output", type=Path, default=ROOT / "tests/evidence/comfy-env-installed-guards.json")
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    command = ["docker", "run", "--interactive", "--rm", "--platform", "linux/amd64",
               "--entrypoint", "/opt/runtime/venv/bin/python", args.image, "-"]
    output = subprocess.check_output(command, input=PROGRAM, text=True)
    result = json.loads(output.strip().splitlines()[-1])
    result["image_id"] = subprocess.check_output([
        "docker", "image", "inspect", args.image,
        "--format", "{{.Id}}"], text=True).strip()
    path = args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
