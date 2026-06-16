#!/usr/bin/env python3
import torch


if not torch.version.cuda:
    raise SystemExit("The installed torch package does not report a CUDA version")

major, minor, *_ = torch.version.cuda.split(".")
print(f"cu{major}{minor}")
