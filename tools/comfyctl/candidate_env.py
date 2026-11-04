"""Create sealed candidate environments; never select or modify a live prefix."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess

from .node_sources import GPU_PACKAGES

INSTALLER_UID = 1001
GPU_LOCK = Path('/opt/locks/gpu.txt')
GENERATION_ROOT = Path('/workspace/runtime/generations')


class CandidateEnvironmentError(ValueError):
    pass


def frozen_pins(data):
    """Accept only exact wheel requirements and SHA256 hashes, not pip commands."""
    if len(data) > 8 * 1024**2:
        raise CandidateEnvironmentError('Candidate lock exceeds size limit')
    text = data.decode('utf-8')
    pins, logical = {}, ''
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line == '--index-url https://pypi.org/simple':
            continue
        continuation = line.endswith('\\')
        logical += ' ' + line.removesuffix('\\').strip()
        if continuation:
            continue
        match = re.fullmatch(r'\s*([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)((?:\s+--hash=sha256:[0-9a-f]{64})+)\s*', logical)
        if not match:
            raise CandidateEnvironmentError('Candidate lock requires exact versions and SHA256 wheel hashes; options, URLs and markers need prior normalization')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in pins:
            raise CandidateEnvironmentError('Duplicate package in candidate lock: ' + name)
        pins[name] = match[2]
        logical = ''
    if logical or not pins:
        raise CandidateEnvironmentError('Candidate lock is empty or truncated')
    return pins


def verify_gpu_pins(pins, gpu_pins):
    expected = {name: value for name, value in gpu_pins.items() if name in GPU_PACKAGES or name.startswith('nvidia-')}
    actual = {name: value for name, value in pins.items() if name in GPU_PACKAGES or name.startswith('nvidia-')}
    if actual != expected:
        raise CandidateEnvironmentError('Candidate GPU packages differ from the immutable image lock; rebuild the image for GPU/ABI changes')


def seal_tree(root):
    # GPU payload links point at immutable /opt files. Never traverse them or
    # chown their targets while sealing the candidate's private CPU files.
    for path in [root, *root.rglob('*')]:
        if path.is_symlink():
            os.chown(path, 0, 0, follow_symlinks=False)
        else:
            executable = bool(path.stat().st_mode & 0o111)
            os.chown(path, 0, 0)
            path.chmod(0o755 if path.is_dir() or executable else 0o644)


def prepare_environment(generation, name, lock_data, expected_hash, *, timeout=1200):
    """Internal installer API. A successful receipt is not generation validation."""
    if os.geteuid() != 0:
        raise CandidateEnvironmentError('Candidate preparation requires the managed container administrator')
    generation = Path(generation)
    if (generation.parent != GENERATION_ROOT or not re.fullmatch(r'[0-9a-f]{32}', generation.name)
            or generation.resolve() != generation or not generation.is_dir()
            or generation.stat().st_uid != 0 or generation.stat().st_mode & 0o022):
        raise CandidateEnvironmentError('Candidate generation must be a root-owned final generation directory')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name):
        raise CandidateEnvironmentError('Invalid candidate environment name')
    if hashlib.sha256(lock_data).hexdigest() != expected_hash:
        raise CandidateEnvironmentError('Candidate lock hash mismatch')
    pins = frozen_pins(lock_data)
    verify_gpu_pins(pins, frozen_pins(GPU_LOCK.read_bytes()))
    host_lock = frozen_pins(Path('/opt/locks/host.txt').read_bytes())
    if pins.get('comfy-env') != host_lock.get('comfy-env'):
        raise CandidateEnvironmentError('Candidate must keep the reviewed comfy-env SDK version')
    if not 0 < timeout <= 3600:
        raise CandidateEnvironmentError('Candidate install timeout must be between 0 and 3600 seconds')
    if shutil.disk_usage(generation).free < 2 * 1024**3:
        raise CandidateEnvironmentError('Insufficient space for a private candidate environment')
    root = generation / ('environment-' + name)
    # Exclusive reservation: interrupted/failed prefixes are never reused.
    root.mkdir(mode=0o755)
    prefix = root / 'venv'
    scratch = root / 'installer'
    for directory in [prefix, scratch]:
        directory.mkdir(mode=0o700)
        os.chown(directory, INSTALLER_UID, INSTALLER_UID)
    lock = root / 'requirements.txt'
    lock.write_bytes(lock_data)
    lock.chmod(0o644)
    request = {'prefix': str(prefix), 'scratch': str(scratch), 'lock': str(lock), 'lock_sha256': expected_hash,
               'gpu_lock_sha256': hashlib.sha256(GPU_LOCK.read_bytes()).hexdigest(), 'expected_versions': pins}
    (root / 'request.json').write_text(json.dumps(request, indent=2) + '\n')
    command = ['/opt/runtime/venv/bin/python', '-I', '/opt/runtime/control/install_candidate.py', str(root / 'request.json')]
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(scratch), 'TMPDIR': str(scratch),
           'UV_CACHE_DIR': str(scratch / 'cache'), 'UV_LINK_MODE': 'copy', 'UV_PYTHON_DOWNLOADS': 'never',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1'}
    process = None
    try:
        with (root / 'install.log').open('w') as log:
            process = subprocess.Popen(command, env=env, user=INSTALLER_UID, group=INSTALLER_UID,
                                       extra_groups=[], start_new_session=True, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise CandidateEnvironmentError('Candidate installation timed out; active environments were not selected') from None
        if code:
            raise CandidateEnvironmentError('Candidate installation failed; inspect ' + str(root / 'install.log'))
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        receipt = json.loads((scratch / 'receipt.json').read_text())
        if receipt['versions'] != pins or receipt['prefix'] != str(prefix) or receipt['installer_uid'] != INSTALLER_UID:
            raise CandidateEnvironmentError('Candidate installed state disagrees with its request')
        receipt.update(kind='sealed-candidate-environment', lock_sha256=expected_hash,
                       gpu_lock_sha256=request['gpu_lock_sha256'], selected=False,
                       scope='Wheel installation and dependency/GPU-binding checks; no node/API/GPU execution validation')
        # Remove resolver scratch/artifacts; the selected prefix will not keep a
        # second wheel cache. Keep the request, lock and installer log.
        shutil.rmtree(scratch)
        seal_tree(root)
        (root / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        return receipt
    except BaseException:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        seal_tree(root)
        (root / 'failed.json').write_text(json.dumps({'selected': False, 'lock_sha256': expected_hash}) + '\n')
        raise
