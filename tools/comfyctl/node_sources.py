"""Bounded, execution-free source inspection for future candidate installers."""
from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
import urllib.error
import urllib.request
import zlib

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

ARCHIVE_LIMIT = 128 * 1024 * 1024
EXPANDED_LIMIT = 256 * 1024 * 1024
FILE_LIMIT = 32 * 1024 * 1024
TEXT_LIMIT = 2 * 1024 * 1024
MEMBER_LIMIT = 20000
TAR_LIMIT = 288 * 1024 * 1024
GPU_PACKAGES = {'torch', 'torchvision', 'torchaudio', 'triton', 'xformers', 'cuda-bindings', 'cuda-pathfinder'}


class NodeSourceError(ValueError):
    pass


def repository_name(value):
    if value.startswith('https://github.com/'):
        value = value[len('https://github.com/'):].removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise NodeSourceError('Use owner/repository or an exact HTTPS GitHub repository URL')
    return value


def source_identity(repository, commit):
    repository = repository_name(repository)
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise NodeSourceError('Node planning requires a full lowercase 40-character commit SHA')
    return repository, commit


def download(repository, commit):
    repository, commit = source_identity(repository, commit)
    url = f'https://codeload.github.com/{repository}/tar.gz/{commit}'
    request = urllib.request.Request(url, headers={'User-Agent': 'comfyctl-node-source/1'})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read(ARCHIVE_LIMIT + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NodeSourceError('Cannot download pinned node archive from GitHub') from None
    if len(data) > ARCHIVE_LIMIT:
        raise NodeSourceError('Node archive exceeds compressed size limit')
    return data


def archive_files(data):
    """Hash every regular file; retain bounded analysis text without extraction."""
    if len(data) > ARCHIVE_LIMIT:
        raise NodeSourceError('Node archive exceeds compressed size limit')
    files, texts, skipped = {}, {}, []
    root = None
    expanded = 0
    retained = 0
    try:
        # Bound the entire tar stream too: PAX/long-name headers are processed
        # by tarfile before it yields a member and can themselves be oversized.
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            uncompressed = compressed.read(TAR_LIMIT + 1)
        if len(uncompressed) > TAR_LIMIT:
            raise NodeSourceError('Node archive exceeds total tar stream size limit')
        with tarfile.open(fileobj=io.BytesIO(uncompressed), mode='r:') as archive:
            for count, member in enumerate(archive, 1):
                if count > MEMBER_LIMIT:
                    raise NodeSourceError('Node archive has too many members')
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or '\\' in member.name or not path.parts:
                    raise NodeSourceError('Unsafe path in node archive')
                if root is None:
                    root = path.parts[0]
                if root != path.parts[0]:
                    raise NodeSourceError('Node archive must have one top-level directory')
                if member.isdir():
                    continue
                if not member.isfile() or len(path.parts) < 2:
                    raise NodeSourceError('Node archive contains a link or special entry')
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                if relative in files:
                    raise NodeSourceError('Duplicate path in node archive')
                expanded += member.size
                if member.size > FILE_LIMIT or expanded > EXPANDED_LIMIT:
                    raise NodeSourceError('Node archive exceeds expanded size limit')
                stream = archive.extractfile(member)
                if stream is None:
                    raise NodeSourceError('Cannot read node archive entry')
                content = stream.read(FILE_LIMIT + 1)
                if len(content) != member.size:
                    raise NodeSourceError('Node archive entry size mismatch')
                files[relative] = hashlib.sha256(content).hexdigest()
                if path.suffix in {'.py', '.toml', '.txt', '.cfg', '.sh', '.bat', '.ps1'}:
                    if len(content) > TEXT_LIMIT or retained + len(content) > 32 * TEXT_LIMIT:
                        skipped.append(relative)
                        continue
                    try:
                        texts[relative] = content.decode('utf-8-sig')
                        retained += len(content)
                    except UnicodeDecodeError:
                        skipped.append(relative)
    except (tarfile.TarError, EOFError, OSError, zlib.error):
        raise NodeSourceError('Node archive is not a valid gzip tar archive') from None
    if not files or '__init__.py' not in files:
        raise NodeSourceError('Node repository must contain a root __init__.py')
    return dict(sorted(files.items())), texts, sorted(skipped), expanded


def requirement_report(path, lines):
    requirements, opaque, gpu = [], [], []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Index options, includes, editable/VCS requirements need an explicit
        # installer policy; never silently pass them to a resolver.
        try:
            item = Requirement(line)
            if item.url:
                raise InvalidRequirement('Direct URL requires review')
        except InvalidRequirement:
            opaque.append(line)
            continue
        requirements.append(str(item))
        name = canonicalize_name(item.name)
        if name in GPU_PACKAGES or name.startswith('nvidia-'):
            gpu.append(str(item))
    return {'path': path, 'requirements': requirements, 'review_required_lines': opaque, 'gpu_requirements': gpu}


def analyze(repository, commit, data, expected_hash=None):
    repository, commit = source_identity(repository, commit)
    archive_hash = hashlib.sha256(data).hexdigest()
    if expected_hash is not None and (not re.fullmatch(r'[0-9a-f]{64}', expected_hash) or expected_hash != archive_hash):
        raise NodeSourceError('Node archive SHA256 does not match')
    files, texts, skipped, expanded = archive_files(data)
    hooks = sorted(path for path in files if PurePosixPath(path).name in
                   {'install.py', 'prestartup_script.py', 'setup.py'} or PurePosixPath(path).suffix in {'.sh', '.bat', '.ps1'})
    configurations, requirements, calls, parse_errors = {}, [], [], []
    for path, text in sorted(texts.items()):
        name = PurePosixPath(path).name
        if name.startswith('requirements') and name.endswith('.txt'):
            requirements.append(requirement_report(path, text.splitlines()))
        if path.endswith('.toml') and (name.startswith('comfy-env') or name == 'pyproject.toml'):
            try:
                configurations[path] = tomllib.loads(text)
            except (tomllib.TOMLDecodeError, RecursionError):
                parse_errors.append(path)
            if name == 'pyproject.toml' and path in configurations:
                project = configurations[path].get('project', {})
                if isinstance(project, dict) and isinstance(project.get('dependencies'), list):
                    dependencies = project['dependencies']
                    if all(isinstance(value, str) for value in dependencies):
                        requirements.append(requirement_report(path + ':project.dependencies', dependencies))
                    else:
                        parse_errors.append(path)
        if path.endswith('.py'):
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError, RecursionError):
                parse_errors.append(path)
                continue
            for item in ast.walk(tree):
                if isinstance(item, ast.Call):
                    target = item.func.attr if isinstance(item.func, ast.Attribute) else item.func.id if isinstance(item.func, ast.Name) else None
                    if target == 'register_nodes':
                        calls.append({'path': path, 'line': item.lineno})
    worker_configs = {path: value for path, value in configurations.items() if PurePosixPath(path).name == 'comfy-env.toml'}
    native = bool(worker_configs and calls)
    review = []
    if hooks:
        review.append('Install/startup/build hooks require review; no hook was executed')
    if skipped or parse_errors:
        review.append('Some source text could not be fully analyzed')
    if any(item['review_required_lines'] for item in requirements):
        review.append('Requirements contain includes, options, direct URLs or unsupported syntax')
    if any(item['gpu_requirements'] for item in requirements) or any(value.get('cuda') for value in worker_configs.values()):
        review.append('GPU requirements need comparison with the immutable image GPU lock')
    plan = {'schema_version': 1, 'kind': 'node-source-analysis', 'repository': repository, 'commit': commit,
            'archive_sha256': archive_hash, 'expanded_bytes': expanded, 'files': files,
            'classification': 'native-comfy-env-candidate' if native else 'adapter-review-required',
            'classification_evidence': {'worker_configurations': sorted(worker_configs), 'register_nodes_calls': calls},
            'configuration': configurations, 'requirements': requirements, 'hooks': hooks,
            'unparsed_text': sorted(set(skipped + parse_errors)), 'review_required': review,
            'installation_ready': False,
            'scope': 'Static source inspection only; no import, hook, dependency resolution, installation or active selection change'}
    # TOML permits dates; normalize them before calculating reproducible identity.
    plan = json.loads(json.dumps(plan, default=str))
    plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return plan


def plan_source(repository, commit, expected_hash=None, archive=None):
    repository, commit = source_identity(repository, commit)
    if archive is None:
        data = download(repository, commit)
    else:
        if not expected_hash:
            raise NodeSourceError('Offline archive inspection requires --archive-sha256')
        with Path(archive).open('rb') as stream:
            data = stream.read(ARCHIVE_LIMIT + 1)
    return analyze(repository, commit, data, expected_hash)
