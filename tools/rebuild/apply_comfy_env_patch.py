#!/usr/bin/env python3
"""Apply hash-guarded compatibility changes to the exact 0.3.89 wheel.

These are experimental local patches, not upstream-supported settings. Refuse
unknown source bytes instead of attempting a best-effort patch after upgrades.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ORIGINAL = {
    "install/workspace.py": "2bee69c642922c82514dda3db83fe5553220471ffaabfbf2bc6dda1ebfed19bb",
    "isolation/wrap.py": "32ab3fd563ee08719e79765be5e21b049db6900349815b3da53e358f0c67cbb5",
    "environment/cache.py": "27919a3efd7f3596187159438c8f2b829ef5736518d9fee815122c408fbd31e4",
    "isolation/metadata.py": "d50d45626b9919cd36412c6163c2b4a0168bf863c79a65730db7d1efef320844",
    "isolation/workers/_persistent_worker.py": "77e86335ff3417bd2442b5db1033d78770c61d76b77c831fb38cdbe0c79460fb",
}
CUDA_ANCHOR = "    bootstrap_cuda = get_bootstrap_torch_cuda()\n"
CUDA_GUARD = '''
    # runpod-comfyui: explicit GPU-less build target; never infer from a driver.
    requested_cuda = os.environ.get("COMFYCTL_BUILD_CUDA")
    if requested_cuda:
        import re
        if (sys.platform != "linux" or not re.fullmatch(r"[0-9]+\\.[0-9]+", requested_cuda)
                or bootstrap_cuda != requested_cuda or not torch_version):
            raise RuntimeError("Explicit CUDA target must match the installed Linux bootstrap torch")
        log(f"[runpod-comfyui] Explicit build target CUDA {requested_cuda}, torch {torch_version}")
        return (f"https://download.pytorch.org/whl/cu{requested_cuda.replace('.', '')}",
                requested_cuda, requested_cuda.split('.')[0], python_version, torch_version)
'''


ATTENTION_POLICY = '''# Explicit stable backend: do not auto-enable an installed extension.
_worker_attention = os.environ.get("COMFYCTL_WORKER_ATTENTION")
if _worker_attention:
    if _worker_attention not in ("pytorch", "xformers"):
        raise RuntimeError("Unsupported worker attention backend")
    from comfy.cli_args import args as _worker_args
    _worker_args.use_pytorch_cross_attention = _worker_attention == "pytorch"
    _worker_args.disable_xformers = _worker_attention == "pytorch"
    _worker_args.use_sage_attention = False
    _worker_args.use_flash_attention = False
'''


def transformed(name: str, data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != ORIGINAL[name]:
        raise ValueError(f"Refusing to patch unknown comfy-env 0.3.89 source: {name}")
    text = data.decode()
    if name == "install/workspace.py":
        if text.count(CUDA_ANCHOR) != 1:
            raise ValueError("CUDA patch anchor changed")
        text = text.replace(CUDA_ANCHOR, CUDA_ANCHOR + CUDA_GUARD)
    elif name == "environment/cache.py":
        anchor = '    return get_workspace_dir(comfyui_dir) / ".pixi" / "envs" / env_name\n'
        replacement = '''    # Locked uv venvs use the existing SubprocessWorker protocol directly.
    worker_root = os.environ.get("COMFYCTL_WORKER_ROOT")
    if worker_root:
        root = Path(worker_root)
        if not root.is_absolute() or ".pixi" in str(root):
            raise RuntimeError("Worker root must be an absolute non-pixi prefix")
        if not env_name or Path(env_name).name != env_name or env_name in (".", "..") or ".pixi" in env_name:
            raise RuntimeError("Invalid worker environment name")
        return root / env_name
''' + anchor
        if text.count(anchor) != 1:
            raise ValueError("Worker prefix patch anchor changed")
        text = text.replace(anchor, replacement)
    elif name == "isolation/metadata.py":
        anchor = '# Redirect stdout to stderr so any prints from imported code (or pixi/torch\n'
        replacement = ATTENTION_POLICY + '''\n# Metadata scans honor explicit CPU smoke mode; GPU gates never set this.
if os.environ.get("COMFY_CPU") == "1":
    from comfy.cli_args import args as _cli_args
    _cli_args.cpu = True

''' + anchor
        if text.count(anchor) != 1:
            raise ValueError("Metadata CPU patch anchor changed")
        text = text.replace(anchor, replacement)
    elif name == "isolation/workers/_persistent_worker.py":
        anchor = '    if os.environ.get("COMFY_CPU") == "1":\n'
        if text.count(anchor) != 1:
            raise ValueError("Worker attention patch anchor changed")
        policy = "\n".join("    " + line if line else "" for line in ATTENTION_POLICY.splitlines()) + "\n"
        text = text.replace(anchor, policy + anchor)
        anchor = '        if _torch_check.cuda.is_available() and _torch_check.cuda.get_device_capability()[0] >= 8:\n'
        if text.count(anchor) != 1:
            raise ValueError("Worker automatic attention patch anchor changed")
        text = text.replace(anchor, '        if not os.environ.get("COMFYCTL_WORKER_ATTENTION") and _torch_check.cuda.is_available() and _torch_check.cuda.get_device_capability()[0] >= 8:\n')
    else:
        anchor = "        if not env_dir:\n            continue\n        sp, lib = _get_env_paths(env_dir)\n        if not sp:\n            continue\n"
        guard = '''        if not env_dir:
            if os.environ.get("COMFYCTL_REQUIRE_ISOLATION") == "1":
                raise RuntimeError(f"Required isolation environment is missing: {cf}")
            continue
        sp, lib = _get_env_paths(env_dir)
        if not sp:
            if os.environ.get("COMFYCTL_REQUIRE_ISOLATION") == "1":
                raise RuntimeError(f"Required isolation interpreter is invalid: {cf}")
            continue
'''
        if text.count(anchor) != 1:
            raise ValueError("Isolation patch anchor changed")
        text = text.replace(anchor, guard)
        anchor = '    # Propagate per-node settings as env vars so worker subprocesses can see them\n'
        guard = '''    if config_files and not enabled and os.environ.get("COMFYCTL_REQUIRE_ISOLATION") == "1":
        raise RuntimeError("Required process isolation was disabled")

'''
        if text.count(anchor) != 1:
            raise ValueError("Isolation setting patch anchor changed")
        text = text.replace(anchor, guard + anchor)
        anchor = '    env["COMFYUI_ISOLATION_WORKER"] = "1"\n'
        guard = '''    try:
        from comfy.cli_args import args as parent_args
        if getattr(parent_args, "cpu", False):
            env["COMFY_CPU"] = "1"
    except ImportError:
        pass
'''
        if text.count(anchor) != 1:
            raise ValueError("CPU propagation patch anchor changed")
        text = text.replace(anchor, anchor + guard)
    compile(text, name, "exec")
    return text.encode()


def apply(root: Path) -> dict:
    # Validate and transform every file before writing any patch.
    replacements = {name: transformed(name, (root / name).read_bytes()) for name in ORIGINAL}
    for name, data in replacements.items():
        (root / name).write_bytes(data)
    record = {"upstream_version": "0.3.89", "kind": "experimental-build-and-isolation-guards",
              "original": ORIGINAL, "patched": {name: hashlib.sha256(data).hexdigest() for name, data in replacements.items()}}
    (root / "runpod-patch.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Path to installed comfy_env package directory")
    args = parser.parse_args()
    print(json.dumps(apply(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
