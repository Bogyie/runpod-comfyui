"""Resolve only inside an unprivileged scratch directory; never install here."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess

from packaging.requirements import Requirement

from .candidate_env import CandidateEnvironmentError, frozen_pins, verify_gpu_pins, seal_tree


def base_requirements(comfy_requirements, gpu_pins, host_pins, skipped):
    skipped = set(skipped)
    result = []
    for line in comfy_requirements.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.url:
            raise CandidateEnvironmentError('Image worker base contains a direct requirement URL')
        if requirement.name.lower().replace('_', '-') not in skipped:
            result.append(str(requirement))
    result.extend(name + '==' + version for name, version in gpu_pins.items())
    result.extend(name + '==' + host_pins[name] for name in ['comfy-env', 'uv', 'comfy-kitchen', 'comfy-aimdo'])
    return sorted(set(result))


def resolve_environment(generation, requirements, *, timeout=600):
    generation = Path(generation)
    if (os.geteuid() != 0 or generation.parent != Path('/workspace/runtime/generations') or
            not re.fullmatch(r'[0-9a-f]{32}', generation.name) or generation.resolve() != generation or
            generation.stat().st_uid != 0 or generation.stat().st_mode & 0o022):
        raise CandidateEnvironmentError('Dependency resolution requires a root-managed final generation')
    if not 0 < timeout <= 1800:
        raise CandidateEnvironmentError('Invalid dependency resolution timeout')
    gpu = frozen_pins(Path('/opt/locks/gpu.txt').read_bytes())
    host = frozen_pins(Path('/opt/locks/host.txt').read_bytes())
    baseline = json.loads(Path('/opt/runtime/control/baseline.json').read_text())
    lines = base_requirements(Path('/opt/probe/ComfyUI/requirements.txt').read_text(), gpu, host, baseline['worker_ui_packages_omitted'])
    for value in requirements:
        requirement = Requirement(value)
        if requirement.url or requirement.marker:
            raise CandidateEnvironmentError('Resolver input must be normalized package requirements')
        lines.append(str(requirement))
    root = generation / 'resolution'
    root.mkdir(mode=0o755)
    scratch = root / 'scratch'
    scratch.mkdir(mode=0o700)
    os.chown(scratch, 1001, 1001)
    content = ('\n'.join(sorted(set(lines))) + '\n').encode()
    (root / 'requirements.in').write_bytes(content)
    request = {'operation': 'resolve', 'scratch': str(scratch), 'input': str(root / 'requirements.in'),
               'input_sha256': hashlib.sha256(content).hexdigest()}
    (root / 'request.json').write_text(json.dumps(request) + '\n')
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(scratch), 'TMPDIR': str(scratch),
           'UV_CACHE_DIR': str(scratch / 'cache'), 'UV_PYTHON_DOWNLOADS': 'never', 'UV_LINK_MODE': 'copy',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
    process = None
    try:
        with (root / 'resolve.log').open('w') as log:
            process = subprocess.Popen(['/usr/local/bin/python', '-I', '/opt/runtime/control/install_candidate.py', str(root / 'request.json')],
                user=1001, group=1001, extra_groups=[], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                raise CandidateEnvironmentError('Dependency resolution timed out; inspect ' + str(root / 'resolve.log')) from None
        if code:
            raise CandidateEnvironmentError('Dependency resolution failed; inspect ' + str(root / 'resolve.log'))
        data = (scratch / 'requirements.txt').read_bytes()
        pins = frozen_pins(data)
        verify_gpu_pins(pins, gpu)
        if any(pins.get(name) != host[name] for name in ['comfy-env', 'uv', 'comfy-kitchen', 'comfy-aimdo']):
            raise CandidateEnvironmentError('Resolved environment changed a protected image package')
        (root / 'requirements.txt').write_bytes(data)
        (root / 'receipt.json').write_text(json.dumps({'kind':'candidate-wheel-resolution', 'resolver_uid':1001,
            'input_sha256':request['input_sha256'], 'lock_sha256':hashlib.sha256(data).hexdigest(), 'versions':pins,
            'installed':False, 'selected':False}, indent=2, sort_keys=True)+'\n')
        return data
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        shutil.rmtree(scratch)
        seal_tree(root)
