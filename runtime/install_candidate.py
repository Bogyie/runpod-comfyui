"""Installer child: only hash-locked wheels, private prefix, unprivileged UID."""
import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys


def run(*arguments):
    if arguments[0] == '/usr/local/bin/uv':
        arguments = (arguments[0], '--no-config', *arguments[1:])
    subprocess.run(arguments, check=True)


def main():
    if os.getuid() != 1001 or os.geteuid() != 1001 or os.getgroups():
        raise RuntimeError('Candidate installer must use isolated uid 1001 without supplementary groups')
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'Cannot set installer no_new_privs')
    request = json.loads(Path(sys.argv[1]).read_text())
    if request.get('operation') == 'resolve':
        source = Path(request['input'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != request['input_sha256']:
            raise RuntimeError('Resolver input changed')
        # uv retains compatible pins from an existing output as preferences.
        # Private dependencies can change when required, while unused host/UI
        # packages disappear and explicit GPU/SDK constraints remain mandatory.
        (Path(request['scratch']) / 'requirements.txt').write_bytes(Path('/opt/locks/host.txt').read_bytes())
        run('/usr/local/bin/uv', 'pip', 'compile', str(source), '--python', '/usr/local/bin/python',
            '--constraint', '/opt/locks/gpu.txt', '--torch-backend', 'cu128', '--only-binary=:all:',
            '--generate-hashes', '--emit-index-url', '--index-url', 'https://pypi.org/simple',
            '--output-file', str(Path(request['scratch']) / 'requirements.txt'))
        return
    prefix, scratch, lock = (Path(request[key]) for key in ['prefix', 'scratch', 'lock'])
    if hashlib.sha256(lock.read_bytes()).hexdigest() != request['lock_sha256']:
        raise RuntimeError('Candidate lock changed before installation')
    gpu_lock = Path('/opt/locks/gpu.txt')
    if hashlib.sha256(gpu_lock.read_bytes()).hexdigest() != request['gpu_lock_sha256']:
        raise RuntimeError('Image GPU lock changed before installation')
    run('/usr/local/bin/uv', 'venv', '--python', '/usr/local/bin/python', str(prefix))
    sys.path.insert(0, '/opt/runtime/control')
    from gpu_links import link
    links = link(prefix, gpu_lock)
    run('/usr/local/bin/uv', 'pip', 'install', '--python', str(prefix / 'bin/python'), '--require-hashes',
        '--only-binary=:all:', '--no-deps', '--index-url', 'https://pypi.org/simple', '--requirement', str(lock))
    site = prefix / 'lib/python3.11/site-packages'
    run('/usr/local/bin/python', '/opt/probe/apply_comfy_env_patch.py', str(site / 'comfy_env'))
    run('/usr/local/bin/uv', 'pip', 'check', '--python', str(prefix / 'bin/python'))
    versions = {dist.metadata['Name'].lower().replace('_', '-').replace('.', '-'): dist.version
                for dist in importlib.metadata.distributions(path=[str(site)])}
    if versions != request['expected_versions']:
        raise RuntimeError('Installed packages differ from complete candidate lock')
    for item in links['packages'].values():
        for name in item['paths']:
            path = site / name
            source = Path(links['source']) / name
            if name.endswith('.dist-info'):
                if path.is_symlink() or not path.is_dir():
                    raise RuntimeError('Candidate GPU metadata must remain private')
            elif not path.is_symlink() or path.resolve() != source.resolve():
                raise RuntimeError('Candidate GPU payload changed during installation')
    (scratch / 'receipt.json').write_text(json.dumps({'prefix': str(prefix), 'installer_uid': os.getuid(),
        'versions': versions, 'gpu_packages': links['packages'], 'python_abi': links['python_abi'],
        'dependency_check': 'passed', 'sdk_patch': 'applied', 'gpu_payload_bindings': 'unchanged'}) + '\n')


if __name__ == '__main__':
    main()
