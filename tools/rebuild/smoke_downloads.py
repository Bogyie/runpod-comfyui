#!/usr/bin/env python3
"""Opt-in live public HF/Civitai download and Range-resume test (~110 MB).

No credentials are required by the pinned public fixtures. Private/gated access
is a separate test. Payloads stay under .work; only JSON evidence is retained.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from comfyctl.models import ModelStore, Transport, atomic_json, download_http, resolve_civitai, validate_payload

ROOT = Path(__file__).resolve().parents[2]


class RecordingTransport(Transport):
    def __init__(self):
        super().__init__()
        self.requests = []

    def open(self, url, headers=None):
        response = super().open(url, headers)
        # Never record signed redirect URLs or authentication headers.
        self.requests.append({"range": (headers or {}).get("Range"), "status": response.status,
                              "content_range": response.headers.get("Content-Range")})
        return response


def main() -> None:
    fixtures = yaml.safe_load((ROOT / "tests/fixtures/models-smoke.yaml").read_text())["models"]
    work = ROOT / ".work/live-download-smoke"
    store = ModelStore(work / "models", work / "state")
    receipts = [store.add(item["source"], target=item["target"], expected_hash=item["sha256"],
                          file_id=item.get("file_id")) for item in fixtures]
    assert all(row["status"] == "verified" for row in store.status(True))
    transport = RecordingTransport()
    item = fixtures[-1]
    spec = resolve_civitai(item["source"], transport, item["file_id"])
    part = work / "resume.part"
    part.unlink(missing_ok=True)
    with transport.open(spec.url, {"Range": "bytes=0-65535"}) as response:
        etag = response.headers.get("ETag")
        validator = etag if etag and not etag.startswith("W/") else response.headers.get("Last-Modified")
        part.write_bytes(response.read(65536))
    identity = {"source": spec.source, "file_id": spec.file_id, "sha256": spec.expected_hash}
    atomic_json(part.with_name(part.name + ".json"), {"identity": identity, "validator": validator})
    initial_size = part.stat().st_size
    download_http(spec, part, transport)
    actual = validate_payload(part, spec.expected_hash)
    resumed = [r for r in transport.requests if r["range"] == f"bytes={initial_size}-" and r["status"] == 206]
    if not resumed:
        raise RuntimeError("Transfer verified but actual HTTP 206 resume was not observed")
    result = {"kind": "live-public-provider-gates", "receipts": receipts,
              "resume": {"source": spec.source, "file_id": spec.file_id, "partial_bytes": initial_size,
                         "sha256": actual, "size": part.stat().st_size, "requests": transport.requests},
              "scope": "Public files and real Range resume only; private/gated access not certified"}
    atomic_json(ROOT / "tests/evidence/public-download-gates.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
