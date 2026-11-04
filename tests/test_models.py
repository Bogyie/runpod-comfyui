import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
import types
from pathlib import Path
from unittest.mock import patch

from comfyctl.models import (
    ModelError, ModelSpec, ModelStore, ProviderRedirect, atomic_json,
    download_http, resolve_civitai, resolve_hf, safe_target, source_url, Transport as HttpTransport,
)

PAYLOAD = b"model-weights-for-tests"
HASH = hashlib.sha256(PAYLOAD).hexdigest()
SOURCE = "https://civitai.com/models/11?modelVersionId=22"


class Response(io.BytesIO):
    def __init__(self, data=PAYLOAD, status=200, **headers):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data)), "ETag": '"entity-v1"', **headers}


class Transport:
    def __init__(self, responses=None, files=None):
        self.responses = list(responses or [Response()])
        self.calls = []
        self.metadata = {"files": files or [{"id": 33, "name": "weights.safetensors", "type": "Model",
                         "hashes": {"SHA256": HASH}, "downloadUrl": "https://civitai.com/api/download/models/22"}]}

    def json(self, url, headers):
        return self.metadata

    def open(self, url, headers):
        self.calls.append((url, headers.copy()))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ProviderTests(unittest.TestCase):
    def test_metadata_rate_limit_uses_bounded_retry(self):
        client = HttpTransport()
        error = urllib.error.HTTPError('https://provider', 429, 'limited', {'Retry-After': '120'}, None)
        with patch.object(client, 'open', side_effect=[error, Response(b'{"files": []}')]), \
                patch('comfyctl.models.time.sleep') as sleep:
            self.assertEqual(client.json('https://provider'), {'files': []})
            sleep.assert_called_once_with(30)

    def test_hf_nested_file_and_encoded_revision(self):
        spec = resolve_hf("https://huggingface.co/org/repo/blob/refs%2Fpr%2F2/sub/weights.safetensors?download=true")
        self.assertEqual((spec.repo, spec.revision, spec.repo_file), ("org/repo", "refs/pr/2", "sub/weights.safetensors"))
        self.assertNotIn("?", spec.source)

    def test_sources_reject_credentials_and_wrong_providers(self):
        for value in ["https://secret@civitai.com/a", "https://civitai.com/a?token=secret", "http://civitai.com/a"]:
            with self.subTest(value=value), self.assertRaises(ModelError):
                source_url(value)
        with self.assertRaises(ModelError):
            resolve_hf("https://example.com/org/repo/resolve/main/file")

    def test_civitai_requires_explicit_version_and_ambiguous_file_selection(self):
        with self.assertRaisesRegex(ModelError, "modelVersionId"):
            resolve_civitai("https://civitai.com/models/11", Transport())
        files = Transport().metadata["files"]
        files.append({**files[0], "id": 44, "name": "other.safetensors"})
        with self.assertRaisesRegex(ModelError, "--file-id"):
            resolve_civitai(SOURCE, Transport(files=files))
        self.assertEqual(resolve_civitai(SOURCE, Transport(files=files), 44).file_id, 44)

    def test_redirect_strips_auth_only_when_origin_changes(self):
        handler = ProviderRedirect()
        req = urllib.request.Request("https://civitai.com/start", headers={"Authorization": "Bearer secret", "Cookie": "secret"})
        redirected = handler.redirect_request(req, None, 302, "", {}, "https://cdn.example.com/weights")
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertIsNone(redirected.get_header("Cookie"))
        same = handler.redirect_request(req, None, 302, "", {}, "https://civitai.com/next")
        self.assertEqual(same.get_header("Authorization"), "Bearer secret")
        with self.assertRaises(ModelError):
            handler.redirect_request(req, None, 302, "", {}, "http://example.com/weights")

    def test_path_traversal_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            for target in ["../weights", "loras/../../weights", "/tmp/weights", "loras/.hidden", "unknown/file"]:
                with self.subTest(target=target), self.assertRaises(ModelError):
                    safe_target(root, target)
            (root / "loras").symlink_to(outside)
            with self.assertRaises(ModelError):
                safe_target(root, "loras/weights")


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = ModelSpec("civitai", "version22", "weights", url="https://civitai.com/weights", expected_hash=HASH, file_id=33)

    def stamp(self, part, validator='"entity-v1"', file_id=33):
        atomic_json(part.with_name(part.name + ".json"), {"identity": {"source": self.spec.source,
                    "sha256": HASH, "file_id": file_id}, "validator": validator})

    def test_resume_uses_validator_and_range(self):
        part = self.root / "weights.part"
        part.write_bytes(PAYLOAD[:5])
        self.stamp(part)
        transport = Transport([Response(PAYLOAD[5:], 206, **{"Content-Range": f"bytes 5-{len(PAYLOAD)-1}/{len(PAYLOAD)}"})])
        download_http(self.spec, part, transport)
        self.assertEqual(part.read_bytes(), PAYLOAD)
        self.assertEqual(transport.calls[0][1]["Range"], "bytes=5-")
        self.assertEqual(transport.calls[0][1]["If-Range"], '"entity-v1"')

    def test_server_ignoring_range_replaces_partial_instead_of_appending(self):
        part = self.root / "weights.part"
        part.write_bytes(b"outdated")
        self.stamp(part)
        download_http(self.spec, part, Transport())
        self.assertEqual(part.read_bytes(), PAYLOAD)

    def test_expected_content_hash_allows_resume_without_etag(self):
        part = self.root / 'weights.part'
        part.write_bytes(PAYLOAD[:5])
        self.stamp(part, validator=None)
        transport = Transport([Response(PAYLOAD[5:], 206, **{'Content-Range': f'bytes 5-{len(PAYLOAD)-1}/{len(PAYLOAD)}'})])
        download_http(self.spec, part, transport)
        self.assertEqual(transport.calls[0][1]['Range'], 'bytes=5-')
        self.assertNotIn('If-Range', transport.calls[0][1])
        self.assertEqual(part.read_bytes(), PAYLOAD)

    def test_other_file_identity_does_not_reuse_partial(self):
        part = self.root / "weights.part"
        part.write_bytes(b"wrong-file")
        self.stamp(part, file_id=99)
        transport = Transport()
        download_http(self.spec, part, transport)
        self.assertNotIn("Range", transport.calls[0][1])
        self.assertEqual(part.read_bytes(), PAYLOAD)

    def test_malformed_range_never_appends(self):
        part = self.root / "weights.part"
        part.write_bytes(PAYLOAD[:5])
        self.stamp(part)
        transport = Transport([Response(b"wrong", 206, **{"Content-Range": "bytes 0-4/5"})])
        with self.assertRaisesRegex(ModelError, "ranged"):
            download_http(self.spec, part, transport)
        self.assertEqual(part.read_bytes(), PAYLOAD[:5])

    def test_rate_limit_retries_and_auth_errors_do_not(self):
        limited = urllib.error.HTTPError("https://provider", 429, "limited", {"Retry-After": "0"}, None)
        transport = Transport([limited, Response()])
        with patch("comfyctl.models.time.sleep"):
            download_http(self.spec, self.root / "weights.part", transport)
        self.assertEqual(len(transport.calls), 2)
        denied = urllib.error.HTTPError("https://provider?secret", 403, "denied", {}, None)
        with self.assertRaisesRegex(ModelError, "denied access") as caught:
            download_http(self.spec, self.root / "denied.part", Transport([denied]))
        self.assertNotIn("secret", str(caught.exception))

    def test_low_disk_prevents_payload_write(self):
        with patch("comfyctl.models.shutil.disk_usage") as disk:
            disk.return_value.free = 1
            with self.assertRaisesRegex(ModelError, "disk space"):
                download_http(self.spec, self.root / "weights.part", Transport())
        self.assertFalse((self.root / "weights.part").exists())

    def test_completed_partial_after_crash_can_publish_without_redownload(self):
        part = self.root / 'weights.part'
        part.write_bytes(PAYLOAD)
        self.stamp(part)
        stamp = json.loads(part.with_name(part.name + '.json').read_text())
        stamp['total'] = len(PAYLOAD)
        atomic_json(part.with_name(part.name + '.json'), stamp)
        transport = Transport()
        download_http(self.spec, part, transport)
        self.assertEqual(transport.calls, [])

    def test_hf_uses_resolved_commit_and_does_not_keep_duplicate_payload(self):
        store = ModelStore(self.root / 'models', self.root / 'state')
        metadata = types.SimpleNamespace(size=len(PAYLOAD), commit_hash='a' * 40)

        def hf_download(**kwargs):
            self.assertEqual(kwargs['revision'], 'a' * 40)
            target = Path(kwargs['local_dir']) / 'sub/weights.safetensors'
            target.parent.mkdir(parents=True)
            target.write_bytes(PAYLOAD)
            return str(target)

        with patch('huggingface_hub.get_hf_file_metadata', return_value=metadata), \
                patch('huggingface_hub.hf_hub_download', side_effect=hf_download):
            receipt = store.add('https://huggingface.co/org/repo/resolve/main/sub/weights.safetensors', 'loras')
        self.assertEqual(receipt['revision'], 'a' * 40)
        self.assertEqual(receipt['sha256'], HASH)
        self.assertEqual(list((self.root / 'models').rglob('*.safetensors')), [self.root / 'models/loras/weights.safetensors'])

    def test_publish_is_verified_and_repeated_add_is_idempotent(self):
        transport = Transport()
        store = ModelStore(self.root / "models", self.root / "state", transport)
        receipt = store.add(SOURCE, "loras")
        self.assertEqual(receipt["sha256"], HASH)
        self.assertEqual((self.root / "models/loras/weights.safetensors").read_bytes(), PAYLOAD)
        self.assertEqual(store.add(SOURCE, "loras"), receipt)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(store.status(True)[0]["status"], "verified")

    def test_hash_mismatch_and_html_do_not_publish(self):
        for payload in [b"wrong-hash", b"<!DOCTYPE html><html>login</html>"]:
            with self.subTest(payload=payload):
                store = ModelStore(self.root / "models", self.root / "state", Transport([Response(payload)]))
                with self.assertRaises(ModelError):
                    store.add(SOURCE, "loras")
                self.assertFalse((self.root / "models/loras/weights.safetensors").exists())
                self.assertEqual(store.records(), {})


if __name__ == "__main__":
    unittest.main()
