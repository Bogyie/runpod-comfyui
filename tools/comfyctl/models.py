"""Provider-aware model downloads, isolated from ComfyUI's Python environment."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Iterator

MODEL_TYPES = frozenset({
    "checkpoints", "diffusion_models", "text_encoders", "clip", "clip_vision",
    "vae", "loras", "controlnet", "upscale_models", "embeddings", "model_patches",
    "audio_encoders", "geometry_estimation", "diffusers", "style_models",
})
HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


class ModelError(Exception):
    """An actionable model operation error; never contains credential-bearing URLs."""


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise ModelError("Target must be a relative path string")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "\x00" in value:
        raise ModelError("Target must be a relative path within the model directory")
    if any(part.startswith(".") for part in path.parts) or not path.parts:
        raise ModelError("Hidden or empty model targets are not allowed")
    return path


def safe_target(root: Path, value: str) -> Path:
    relative = relative_path(value)
    if relative.parts[0] not in MODEL_TYPES or len(relative.parts) < 2:
        raise ModelError("Target must start with a supported model type and include a filename")
    base = root.resolve()
    target = base.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(base):
        raise ModelError("Target escapes the model directory through a symlink")
    if target.is_symlink():
        raise ModelError("Refusing to overwrite a model symlink")
    return target


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validate_payload(path: Path, expected_hash: str | None = None) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise ModelError("Download is empty")
    with path.open("rb") as stream:
        prefix = stream.read(256).lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<?xml", b'{"error"')):
        raise ModelError("Provider returned an error/login page instead of a model")
    actual = sha256(path)
    if expected_hash and actual.lower() != expected_hash.lower():
        raise ModelError("SHA256 mismatch; incomplete file was not published")
    return actual


class ProviderRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if new.scheme != "https" and not (old.scheme == new.scheme == "http" and new.hostname in {"127.0.0.1", "localhost"}):
            raise ModelError("Refusing a redirect to an insecure download endpoint")
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None and (old.scheme, old.netloc) != (new.scheme, new.netloc):
            result.remove_header("Authorization")
            result.remove_header("Cookie")
        return result


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(ProviderRedirect())

    def open(self, url: str, headers: dict | None = None):
        request = urllib.request.Request(url, headers={"User-Agent": "runpod-comfyctl/0.1", **(headers or {})})
        return self.opener.open(request, timeout=60)

    def json(self, url: str, headers: dict | None = None) -> dict:
        for attempt in range(4):
            try:
                with self.open(url, headers) as response:
                    data = response.read(8 * 1024 * 1024 + 1)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                    raise
                retry_after = exc.headers.get("Retry-After", "")
                delay = min(int(retry_after), 30) if retry_after.isdigit() else 2 ** attempt
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise
                delay = 2 ** attempt
            time.sleep(delay)
        if len(data) > 8 * 1024 * 1024:
            raise ModelError("Provider metadata is too large")
        return json.loads(data)


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    source: str
    filename: str
    url: str | None = None
    repo: str | None = None
    revision: str | None = None
    repo_file: str | None = None
    expected_hash: str | None = None
    version_id: int | None = None
    file_id: int | None = None


def source_url(value: str):
    if not isinstance(value, str):
        raise ModelError("Model source must be a URL string")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ModelError("Use an HTTPS Hugging Face or Civitai URL without embedded credentials")
    query = urllib.parse.parse_qs(parsed.query)
    if any(key.lower() in {"token", "access_token", "api_key", "apikey", "auth"} for key in query):
        raise ModelError("Pass credentials through HF_TOKEN/CIVITAI_TOKEN, not URL query parameters")
    return parsed, query


def resolve_hf(value: str) -> ModelSpec:
    parsed, _ = source_url(value)
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname != "huggingface.co" or len(parts) < 5 or parts[2] not in {"resolve", "blob"}:
        raise ModelError("HF URL must identify a repository, revision, and file")
    repo = "/".join(parts[:2])
    revision = urllib.parse.unquote(parts[3])
    filename = urllib.parse.unquote("/".join(parts[4:]))
    relative_path(filename)
    canonical = f"https://huggingface.co/{repo}/resolve/{urllib.parse.quote(revision, safe='')}/{urllib.parse.quote(filename, safe='/')}"
    return ModelSpec("huggingface", canonical, PurePosixPath(filename).name, repo=repo, revision=revision, repo_file=filename)


def resolve_civitai(value: str, transport: Transport, selected_file: int | None = None) -> ModelSpec:
    parsed, query = source_url(value)
    if parsed.hostname not in {"civitai.com", "www.civitai.com"}:
        raise ModelError("Unsupported model provider")
    segments = parsed.path.strip("/").split("/")
    if segments[:3] == ["api", "download", "models"] and len(segments) == 4:
        version = segments[3]
    elif len(segments) >= 2 and segments[0] == "models":
        version = query.get("modelVersionId", [None])[0]
        if version is None:
            raise ModelError("Civitai model URL needs modelVersionId; choose a specific version")
    else:
        raise ModelError("Use a Civitai model page with modelVersionId or a download URL")
    if not version.isdigit():
        raise ModelError("Civitai version ID must be numeric")
    token = os.environ.get("CIVITAI_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        metadata = transport.json(f"https://civitai.com/api/v1/model-versions/{version}", headers)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise ModelError(f"Civitai denied access ({exc.code}); check CIVITAI_TOKEN and model access") from None
        raise ModelError(f"Civitai metadata request returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise ModelError("Civitai metadata request failed; check connectivity and version ID") from None
    files = [f for f in metadata.get("files", []) if f.get("type") == "Model"]
    if selected_file is not None:
        files = [f for f in files if f.get("id") == selected_file]
    if len(files) != 1:
        candidates = ", ".join(f"{f.get('id')}: {f.get('name')}" for f in files)
        raise ModelError("Choose --file-id from model files: " + (candidates or "none available"))
    item = files[0]
    name = item["name"]
    if relative_path(name).name != name:
        raise ModelError("Civitai returned an unsafe filename")
    url = item["downloadUrl"]
    download, _ = source_url(url)
    if download.hostname not in {"civitai.com", "www.civitai.com"}:
        raise ModelError("Civitai metadata returned an unexpected download host")
    expected = item.get("hashes", {}).get("SHA256")
    if expected and not HASH.fullmatch(expected):
        raise ModelError("Provider SHA256 metadata is malformed")
    return ModelSpec("civitai", f"https://civitai.com/api/download/models/{version}", name,
                     url=url, expected_hash=expected, version_id=int(version), file_id=item["id"])


def download_http(spec: ModelSpec, part: Path, transport: Transport, attempts: int = 4) -> None:
    """Resume using an entity validator or an immutable expected content hash."""
    stamp = part.with_name(part.name + ".json")
    identity = {"source": spec.source, "file_id": spec.file_id, "sha256": spec.expected_hash}
    try:
        previous = json.loads(stamp.read_text()) if stamp.is_file() else {}
    except ValueError:
        previous = {}
    if previous.get("identity") != identity:
        part.unlink(missing_ok=True)
        previous = {}
    if part.exists() and (previous.get("complete") or
                         (spec.expected_hash and part.stat().st_size == previous.get("total"))):
        try:
            validate_payload(part, spec.expected_hash)
            return
        except ModelError:
            part.unlink()
            previous = {}
    token = os.environ.get("CIVITAI_TOKEN") if spec.provider == "civitai" else None
    for attempt in range(attempts):
        offset = part.stat().st_size if part.exists() else 0
        validator = previous.get("validator")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if offset and (validator or spec.expected_hash):
            headers["Range"] = f"bytes={offset}-"
            if validator:
                headers["If-Range"] = validator
        else:
            offset = 0
        try:
            with transport.open(spec.url, headers) as response:
                status = response.status
                if status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not offset or not match or int(match[1]) != offset:
                        raise ModelError("Invalid ranged download response")
                    if int(match[2]) != int(match[3]) - 1:
                        raise ModelError("Provider did not return the complete remaining file")
                    total = int(match[3])
                    new_etag = response.headers.get("ETag")
                    new_validator = new_etag if new_etag and not new_etag.startswith("W/") else response.headers.get("Last-Modified")
                    if validator and new_validator and new_validator != validator:
                        part.unlink(missing_ok=True)
                        previous = {}
                        raise ConnectionError("Download entity changed during resume")
                elif status == 200:
                    offset = 0
                    total = int(response.headers["Content-Length"]) if response.headers.get("Content-Length") else None
                else:
                    raise ModelError(f"Unexpected download HTTP status {status}")
                if "text/html" in response.headers.get("Content-Type", "").lower():
                    raise ModelError("Provider returned an HTML page instead of a model")
                if total is not None and shutil.disk_usage(part.parent).free < total - offset + 16 * 1024 * 1024:
                    raise ModelError("Insufficient free disk space for model download")
                etag = response.headers.get("ETag")
                validator = etag if etag and not etag.startswith("W/") else response.headers.get("Last-Modified")
                previous = {"identity": identity, "validator": validator, "total": total}
                atomic_json(stamp, previous)
                with part.open("ab" if offset else "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if total is not None and part.stat().st_size != total:
                    raise ConnectionError("Incomplete model download")
                atomic_json(stamp, {**previous, "complete": True})
                return
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ModelError(f"Provider denied access ({exc.code}); check token and model access/license") from None
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise ModelError(f"Provider returned HTTP {exc.code}") from None
            retry_after = exc.headers.get("Retry-After", "")
            delay = min(int(retry_after), 30) if retry_after.isdigit() else 2 ** attempt
            time.sleep(delay)
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead):
            if attempt == attempts - 1:
                raise ModelError("Download interrupted; rerun the command to resume") from None
        time.sleep(2 ** attempt)


class ModelStore:
    def __init__(self, root: Path, state: Path, transport: Transport | None = None):
        self.root = root
        self.state = state
        self.transport = transport or Transport()

    def add(self, source: str, model_type: str | None = None, target: str | None = None,
            expected_hash: str | None = None, file_id: int | None = None) -> dict:
        if expected_hash and not HASH.fullmatch(expected_hash):
            raise ModelError("--sha256 must be a 64-digit hexadecimal hash")
        parsed, _ = source_url(source)
        spec = resolve_hf(source) if parsed.hostname == "huggingface.co" else resolve_civitai(source, self.transport, file_id)
        if expected_hash and spec.expected_hash and expected_hash.lower() != spec.expected_hash.lower():
            raise ModelError("Requested SHA256 disagrees with provider metadata")
        expected_hash = expected_hash or spec.expected_hash
        spec = replace(spec, expected_hash=expected_hash)
        if target is None:
            if model_type not in MODEL_TYPES:
                raise ModelError("Specify --type or a target beginning with a model type")
            target = f"{model_type}/{spec.filename}"
        elif model_type and relative_path(target).parts[0] != model_type:
            raise ModelError("--type disagrees with target directory")
        destination = safe_target(self.root, target)
        key = hashlib.sha256(str(destination).encode()).hexdigest()
        with locked(self.state / "locks" / f"{key}.lock"):
            destination = safe_target(self.root, target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            existing = self.records().get(target)
            if destination.exists():
                if expected_hash:
                    actual = validate_payload(destination, expected_hash)
                elif existing and existing["source"] == spec.source:
                    actual = validate_payload(destination, existing["sha256"])
                else:
                    raise ModelError("Target already exists without a matching receipt/hash; choose another target")
            else:
                staging = destination.with_name("." + destination.name + ".download")
                if staging.is_symlink():
                    raise ModelError("Refusing a symlink in download staging")
                staging.mkdir(parents=True, exist_ok=True)
                # Staging must share the destination filesystem for atomic publication.
                # Put the payload beside its final path, with a fixed per-target lock.
                part = destination.with_name("." + destination.name + ".part")
                if part.is_symlink() or part.with_name(part.name + ".json").is_symlink():
                    raise ModelError("Refusing a symlink in download staging")
                if spec.provider == "huggingface":
                    try:
                        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
                        token = os.environ.get("HF_TOKEN")
                        metadata = get_hf_file_metadata(hf_hub_url(repo_id=spec.repo, filename=spec.repo_file,
                                                                 revision=spec.revision), token=token)
                        if metadata.size and shutil.disk_usage(destination.parent).free < metadata.size + 16 * 1024 * 1024:
                            raise ModelError("Insufficient free disk space for HF model download")
                        spec = replace(spec, revision=metadata.commit_hash or spec.revision)
                        hf_path = hf_hub_download(repo_id=spec.repo, filename=spec.repo_file,
                                                 revision=spec.revision, token=token,
                                                 local_dir=staging / "hf")
                        # Same filesystem: publish by rename instead of duplicating multi-GB files.
                        os.replace(hf_path, part)
                    except ImportError:
                        raise ModelError("Install comfyctl with its huggingface-hub dependency") from None
                    except ModelError:
                        raise
                    except Exception:
                        raise ModelError("HF download failed; check connectivity, HF_TOKEN and gated repository access") from None
                else:
                    download_http(spec, part, self.transport)
                try:
                    actual = validate_payload(part, expected_hash)
                except ModelError:
                    # A complete but invalid entity cannot be repaired by Range-resuming at EOF.
                    part.unlink(missing_ok=True)
                    part.with_name(part.name + ".json").unlink(missing_ok=True)
                    raise
                os.replace(part, destination)
                part.with_name(part.name + ".json").unlink(missing_ok=True)
                shutil.rmtree(staging, ignore_errors=True)
            receipt = {"provider": spec.provider, "source": spec.source, "sha256": actual,
                       "size": destination.stat().st_size, "target": target,
                       "revision": spec.revision, "version_id": spec.version_id, "file_id": spec.file_id}
            with locked(self.state / "receipts.lock"):
                records = self.records()
                records[target] = receipt
                atomic_json(self.state / "models.json", records)
            return receipt

    def records(self) -> dict:
        path = self.state / "models.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def status(self, verify: bool = False) -> list[dict]:
        results = []
        for target, record in self.records().items():
            path = safe_target(self.root, target)
            state = "present" if path.is_file() else "missing"
            if state == "present" and verify:
                state = "verified" if sha256(path) == record["sha256"] else "changed"
            results.append({**record, "status": state})
        return results
