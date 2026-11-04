#!/usr/bin/env python3
"""Share only pinned, immutable GPU package files with a same-ABI worker venv.

This never adds the host site-packages directory to sys.path. All other worker
packages remain independent. Runtime users must not be able to write the source
GPU installation. Candidate environments with a different GPU ABI need their own
GPU packages instead of this optimization.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path, PurePosixPath


def canonical(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def shared(name: str) -> bool:
    return name in {'torch','torchvision','torchaudio','triton','xformers','cuda-bindings','cuda-pathfinder'} or name.startswith('nvidia-')


def link(prefix: Path, lock: Path) -> dict:
    if not prefix.is_absolute() or prefix.resolve() == Path(sys.prefix).resolve():
        raise ValueError('Worker must have a separate absolute prefix')
    config = (prefix/'pyvenv.cfg').read_text().lower()
    if not re.search(r'include-system-site-packages\s*=\s*false', config):
        raise ValueError('Worker must not include system site-packages')
    worker = json.loads(subprocess.check_output([str(prefix/'bin/python'), '-I', '-c',
        'import json,sys,sysconfig;print(json.dumps({"site":sysconfig.get_path("purelib"),"abi":sys.implementation.cache_tag,"prefix":sys.prefix}))'],text=True))
    if worker['abi'] != sys.implementation.cache_tag or Path(worker['prefix']) != prefix:
        raise ValueError('Worker Python ABI or final prefix does not match')
    target = Path(worker['site'])
    source = Path(sysconfig.get_path('purelib'))
    if source == target or not target.is_relative_to(prefix):
        raise ValueError('Invalid worker site-packages')
    pins = {canonical(m[1]):m[2] for m in re.finditer(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)',lock.read_text(),re.M)}
    required = {name:version for name,version in pins.items() if shared(name)}
    installed = {canonical(d.metadata['Name']):d for d in importlib.metadata.distributions(path=[str(source)])}
    destinations = {}
    packages = {}
    scripts = {}
    # Validate every package before making any link.
    for name,version in required.items():
        dist = installed.get(name)
        if dist is None or dist.version != version or not dist.files:
            raise ValueError(f'Source GPU package does not match lock: {name}=={version}')
        tops = set()
        for entry in dist.files:
            parts = PurePosixPath(str(entry)).parts
            if not parts or parts[0] in {'.','..','/'}:
                continue
            top = parts[0]
            origin = source/top
            if not origin.exists() or not origin.resolve().is_relative_to(source.resolve()):
                raise ValueError(f'Unexpected GPU distribution path: {entry}')
            dest = target/top
            if dest.exists() or dest.is_symlink():
                raise ValueError(f'Worker package path already exists: {dest}')
            destinations[dest] = origin
            tops.add(top)
        for ep in dist.entry_points:
            if ep.group == 'console_scripts':
                if not re.fullmatch(r'[A-Za-z0-9_.-]+',ep.name) or (prefix/'bin'/ep.name).exists():
                    raise ValueError(f'Unsafe or existing GPU console script: {ep.name}')
                scripts[ep.name] = (dist.metadata['Name'],ep.name)
        packages[name] = {'version':version,'paths':sorted(tops)}
    if not {'torch','torchvision','torchaudio','triton','xformers'}.issubset(packages):
        raise ValueError('Incomplete GPU lock')
    for dest,origin in destinations.items():
        # uv deliberately ignores symlinked dist-info directories. Metadata is
        # small and must belong to the worker; only binary payloads are shared.
        if dest.name.endswith('.dist-info'):
            shutil.copytree(origin,dest)
        else:
            dest.symlink_to(origin, target_is_directory=origin.is_dir())
    for filename,(distribution,entrypoint) in scripts.items():
        script = prefix/'bin'/filename
        script.write_text(f'#!{prefix}/bin/python\nimport sys\nfrom importlib.metadata import distribution\nsys.exit(next(ep for ep in distribution({distribution!r}).entry_points if ep.group == "console_scripts" and ep.name == {entrypoint!r}).load()())\n')
        script.chmod(0o755)
    result = {'kind':'immutable-gpu-package-links','python_abi':worker['abi'],'source':str(source),
              'worker_prefix':str(prefix),'packages':packages,'host_site_packages_on_sys_path':False,
              'requirement':'Source GPU installation is immutable to the runtime user'}
    (prefix/'gpu-links.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix',type=Path)
    parser.add_argument('--gpu-lock',type=Path,default=Path('/opt/locks/gpu.txt'))
    args = parser.parse_args()
    result = link(args.prefix,args.gpu_lock)
    print(f"Linked {len(result['packages'])} pinned GPU packages into {args.prefix}")


if __name__ == '__main__':
    main()
