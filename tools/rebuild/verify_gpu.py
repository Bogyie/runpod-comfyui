#!/usr/bin/env python3
"""Run real GPU kernel gates; never treat a missing GPU as a passing check.

This proves kernel coverage only. Node workflows, worker isolation and RunPod
lifecycle tests remain additional gates before stable promotion.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import subprocess
import time
from pathlib import Path


def probe(expected_cc: str, expected_cuda: str) -> dict:
    import torch
    import torch.nn.functional as F

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required; this check cannot pass on a CPU runner")
    device = torch.device("cuda:0")
    cc = ".".join(map(str, torch.cuda.get_device_capability(device)))
    if cc != expected_cc:
        raise RuntimeError(f"Expected compute capability {expected_cc}, got {cc}")
    if torch.version.cuda != expected_cuda:
        raise RuntimeError(f"Expected CUDA runtime {expected_cuda}, got {torch.version.cuda}")
    torch.manual_seed(12345)
    torch.cuda.reset_peak_memory_stats(device)
    start = time.monotonic()
    with torch.inference_mode():
        a = torch.randn((256, 256), device=device, dtype=torch.bfloat16)
        b = torch.randn((256, 256), device=device, dtype=torch.bfloat16)
        product = a @ b
        reference = a.cpu().float() @ b.cpu().float()
        if not torch.isfinite(product).all() or not torch.allclose(product.float().cpu(), reference, atol=0.3, rtol=0.03):
            raise RuntimeError("BF16 matrix multiplication disagrees with CPU reference")
        q, k, v = [torch.randn((1, 4, 128, 64), device=device, dtype=torch.bfloat16) for _ in range(3)]
        reference = F.scaled_dot_product_attention(q.cpu().float(), k.cpu().float(), v.cpu().float())
        sdpa = F.scaled_dot_product_attention(q, k, v)
        if not torch.isfinite(sdpa).all() or not torch.allclose(sdpa.float().cpu(), reference, atol=0.03, rtol=0.03):
            raise RuntimeError("PyTorch SDPA disagrees with CPU reference")
        from xformers.ops import memory_efficient_attention
        xf = memory_efficient_attention(q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2)).transpose(1, 2)
        if not torch.isfinite(xf).all() or not torch.allclose(xf.float().cpu(), reference, atol=0.03, rtol=0.03):
            raise RuntimeError("xformers attention disagrees with CPU reference")
        torch.cuda.synchronize(device)
    try:
        driver = subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True).strip().splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        raise RuntimeError("Driver version could not be recorded with nvidia-smi") from None
    return {
        "gpu": torch.cuda.get_device_name(device), "compute_capability": cc,
        "cuda_runtime": torch.version.cuda, "driver": driver,
        "python": platform.python_version(),
        "packages": {name: importlib.metadata.version(name) for name in ["torch", "torchvision", "torchaudio", "xformers", "triton"]},
        "checks": {"bf16_matmul": "passed", "sdpa_bf16": "passed", "xformers_bf16": "passed"},
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "seconds": time.monotonic() - start,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-cc", required=True, choices=["9.0", "12.0"])
    parser.add_argument("--expected-cuda", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image_digest):
        parser.error("image digest must be an immutable sha256 digest")
    # No success artifact is emitted when any kernel/metadata check fails.
    args.output.unlink(missing_ok=True)
    result = probe(args.expected_cc, args.expected_cuda)
    result.update({"kind": "gpu-kernel-gate", "image_digest": args.image_digest,
                   "scope": "GPU kernels only; no custom-node or lifecycle certification"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
