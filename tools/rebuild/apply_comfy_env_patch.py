#!/usr/bin/env python3
"""Apply two narrowly scoped P0 compatibility guards to the exact 0.3.89 wheel.

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


def transformed(name: str, data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != ORIGINAL[name]:
        raise ValueError(f"Refusing to patch unknown comfy-env 0.3.89 source: {name}")
    text = data.decode()
    if name == "install/workspace.py":
        if text.count(CUDA_ANCHOR) != 1:
            raise ValueError("CUDA patch anchor changed")
        text = text.replace(CUDA_ANCHOR, CUDA_ANCHOR + CUDA_GUARD)
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
