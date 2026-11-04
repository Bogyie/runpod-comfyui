#!/usr/bin/env python3
import json
import os
import platform
import re
import ssl
import sys
import sysconfig
import urllib.request


API_URL = "https://api.github.com/repos/mjun0812/flash-attention-prebuild-wheels/releases?per_page=100"


def normalize_arch() -> str:
    arch = platform.machine().lower()
    if arch in {"amd64", "x86_64"}:
        return "x86_64"
    if arch in {"arm64", "aarch64"}:
        return "aarch64"
    raise RuntimeError(f"Unsupported architecture for flash-attn prebuilt wheel: {arch}")


def python_tags() -> list[str]:
    major = sys.version_info.major
    minor = sys.version_info.minor
    impl = f"cp{major}{minor}"
    abi = impl
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        abi = f"{impl}t"
    return [f"{impl}-{abi}", f"{impl}-abi3", "cp39-abi3"]


def torch_cuda_tags() -> tuple[str, str]:
    import torch

    torch_version = re.match(r"(\d+\.\d+)", torch.__version__)
    if not torch_version:
        raise RuntimeError(f"Cannot parse torch version: {torch.__version__}")
    if not torch.version.cuda:
        raise RuntimeError("The installed torch package does not report a CUDA version")

    cuda_parts = torch.version.cuda.split(".")
    cuda_tag = f"cu{cuda_parts[0]}{cuda_parts[1]}"
    return torch_version.group(1), cuda_tag


def release_assets():
    request = urllib.request.Request(API_URL, headers={"User-Agent": "runpod-comfyui-build"})
    context = ssl.create_default_context()
    if os.environ.get("FLASH_ATTN_INSECURE_SSL") == "1":
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        return [
            (release["tag_name"], asset["name"], asset["browser_download_url"])
            for release in json.load(response)
            for asset in release.get("assets", [])
        ]


def main() -> int:
    flash_version = os.environ.get("FLASH_ATTN_VERSION", "2.8.3")
    torch_tag, cuda_tag = torch_cuda_tags()
    arch = normalize_arch()
    py_tags = python_tags()

    candidates = []
    for release_index, (release_tag, name, url) in enumerate(release_assets()):
        if not name.endswith(".whl"):
            continue
        if f"flash_attn-{flash_version}+" not in name:
            continue
        if f"{cuda_tag}torch{torch_tag}" not in name:
            continue
        if arch not in name:
            continue
        if not any(tag in name for tag in py_tags):
            continue
        candidates.append((release_index, release_tag, name, url))

    candidates.sort(key=lambda item: ("manylinux" not in item[2], item[0], item[2]))
    if not candidates:
        wanted = f"flash_attn-{flash_version}+{cuda_tag}torch{torch_tag}-{py_tags[0]}-*{arch}.whl"
        raise RuntimeError(f"No prebuilt flash-attn wheel found for {wanted}")

    print(candidates[0][3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
