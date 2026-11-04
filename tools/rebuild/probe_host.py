#!/usr/bin/env python3
"""Start the P0 host image, submit a model-free graph and verify its PNG output."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def request(base: str, path: str, value=None):
    data = json.dumps(value).encode() if value is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)



def verify_frontend(base: str) -> dict:
    with urllib.request.urlopen(base+'/',timeout=10) as response:
        html = response.read(2*1024*1024)
        if response.status != 200 or b'<html' not in html.lower():
            raise RuntimeError('ComfyUI root did not return its frontend HTML')
    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = []
        def handle_starttag(self, tag, attrs):
            if tag == 'script' and dict(attrs).get('src'):
                self.sources.append(dict(attrs)['src'])
    parser = Scripts()
    parser.feed(html.decode())
    if not parser.sources:
        raise RuntimeError('Frontend HTML did not include a script asset')
    asset = urllib.parse.urljoin(base+'/',parser.sources[0])
    if urllib.parse.urlsplit(asset).netloc != urllib.parse.urlsplit(base).netloc:
        raise RuntimeError('Unexpected external frontend asset')
    with urllib.request.urlopen(asset,timeout=10) as response:
        data = response.read(4*1024*1024)
        if response.status != 200 or not data:
            raise RuntimeError('Frontend entry script was unavailable')
    return {'root_http_status':200,'script':urllib.parse.urlsplit(asset).path,
            'script_bytes':len(data),'script_sha256':hashlib.sha256(data).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="runpod-comfyui:probe-host")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/evidence/host-cpu-probe.json")
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    metadata = json.loads(docker("image", "inspect", args.image))[0]
    if metadata.get("Architecture") != "amd64":
        raise RuntimeError("CPU probe requires the actual amd64 image")
    name = "runpod-comfy-probe-" + uuid.uuid4().hex[:10]
    container = docker("run", "--detach", "--platform", "linux/amd64", "--name", name,
                       "--publish", "127.0.0.1::8188", args.image)
    try:
        details = json.loads(docker("inspect", container))[0]
        port = details["NetworkSettings"]["Ports"]["8188/tcp"][0]["HostPort"]
        base = f"http://127.0.0.1:{port}"
        start = time.monotonic()
        deadline = start + args.timeout
        while True:
            try:
                stats = request(base, "/system_stats")
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                state = json.loads(docker("inspect", container))[0]["State"]
                if not state["Running"]:
                    raise RuntimeError("ComfyUI exited before readiness:\n" + docker("logs", container))
                if time.monotonic() > deadline:
                    raise RuntimeError("ComfyUI readiness timeout:\n" + docker("logs", container))
                time.sleep(1)
        ready_seconds = time.monotonic() - start
        frontend = verify_frontend(base)
        objects = request(base, "/object_info")
        if not {"EmptyImage", "SaveImage"}.issubset(objects):
            raise RuntimeError("Core workflow nodes were not registered")
        graph = {
            "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
            "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "host-probe"}},
        }
        prompt_id = request(base, "/prompt", {"prompt": graph})["prompt_id"]
        deadline = time.monotonic() + args.timeout
        while True:
            history = request(base, f"/history/{prompt_id}")
            if prompt_id in history:
                entry = history[prompt_id]
                if entry["status"]["status_str"] != "success":
                    raise RuntimeError("Model-free core graph failed: " + json.dumps(entry["status"]))
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Model-free graph execution timed out")
            time.sleep(1)
        image = entry["outputs"]["2"]["images"][0]
        query = urllib.parse.urlencode({key: image[key] for key in ["filename", "subfolder", "type"]})
        with urllib.request.urlopen(base + "/view?" + query, timeout=10) as response:
            png = response.read()
        if png[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", png[16:24]) != (64, 64):
            raise RuntimeError("Core graph did not produce the expected 64x64 PNG")
        locks = json.loads(docker("exec", container, "python", "-c",
                           "import hashlib,json,pathlib;print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path('/opt/locks').glob('*.txt')}))"))
        patch_record = json.loads(docker("exec", container, "python", "-c",
                           "import importlib.util,json,pathlib;p=pathlib.Path(importlib.util.find_spec('comfy_env').origin).parent/'runpod-patch.json';print(p.read_text() if p.is_file() else 'null')"))
        result = {"kind": "linux-amd64-core-cpu-gate", "image_id": metadata["Id"],
                  "ready_seconds": round(ready_seconds, 3), "system_stats": stats, "frontend": frontend,
                  "graph": graph, "output_png_sha256": hashlib.sha256(png).hexdigest(),
                  "image_lock_hashes": locks,
                  "comfy_env_patch": patch_record,
                  "scope": "ComfyUI core API and model-free CPU graph only; custom nodes and GPU remain unverified"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        subprocess.run(["docker", "rm", "--force", container], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
