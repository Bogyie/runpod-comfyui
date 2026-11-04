#!/usr/bin/env python3
"""Create fixed-prefix worker venvs from checked locks; run no node install hooks."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from link_gpu_packages import link


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definitions', type=Path, default=Path('/opt/locks/workers/manifest.json'))
    parser.add_argument('--root', type=Path, default=Path('/opt/workers'))
    parser.add_argument('--backend', required=True)
    args = parser.parse_args()
    definitions = json.loads(args.definitions.read_text())
    if definitions.get('gpu_lock_sha256') != hashlib.sha256(Path('/opt/locks/gpu.txt').read_bytes()).hexdigest():
        raise ValueError('Worker installation GPU lock does not match the base image')
    if not args.root.is_absolute() or '.pixi' in str(args.root):
        raise ValueError('Worker root must be an absolute non-pixi path')
    for name, worker in definitions['workers'].items():
        env = worker['environment']
        if not env or Path(env).name != env or env in {'.','..'}:
            raise ValueError('Unsafe worker environment name')
        lock = args.definitions.parent / worker['lock_file']
        if not lock.resolve().is_relative_to(args.definitions.parent.resolve()):
            raise ValueError('Worker lock path escapes manifest directory')
        if hashlib.sha256(lock.read_bytes()).hexdigest() != worker['lock_sha256']:
            raise ValueError(f'Worker lock hash mismatch: {name}')
        prefix = args.root / env
        if prefix.exists():
            raise ValueError(f'Refusing to modify existing worker environment: {prefix}')
        subprocess.run(['uv','venv','--python','/usr/local/bin/python',str(prefix)],check=True)
        link(prefix,Path('/opt/locks/gpu.txt'))
        subprocess.run(['uv','pip','install','--python',str(prefix/'bin/python'),
                        '--require-hashes','--only-binary=:all:','--torch-backend',args.backend,
                        '--requirement',str(lock)],check=True)
        subprocess.run(['uv','pip','check','--python',str(prefix/'bin/python')],check=True)
        (prefix/'worker-lock.json').write_text(json.dumps(worker,indent=2,sort_keys=True)+'\n')


if __name__ == '__main__':
    main()
