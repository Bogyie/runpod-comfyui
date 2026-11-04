#!/usr/bin/env python3
"""Add reviewed KJ tensor worker mappings while preserving upstream host hooks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def apply(destination:Path,source:dict,adapter:Path)->dict:
    if source['commit']!='ab72eda7ffad6280422d71ab7d54d3fb87c0ba18':
        raise ValueError('Unreviewed KJNodes revision')
    policy=json.loads((adapter/'policy.json').read_text())
    if policy['source_commit']!=source['commit'] or not policy['worker_nodes']:
        raise ValueError('Unexpected KJNodes adapter policy')
    originals={}
    names={'__init__.py','utility/utility.py'}|{item['module'].replace('.','/')+'.py' for item in policy['worker_nodes'].values()}
    for name in sorted(names):
        path=destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unsafe KJ source path')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['files'].get(name):
            raise ValueError('Refusing unknown KJNodes source: '+name)
        originals[name]=raw
    assets={}
    for path in adapter.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:continue
        if path.is_symlink():raise ValueError('Unsafe KJ adapter asset')
        assets[path.relative_to(adapter).as_posix()]=path.read_bytes()
    if set(assets)!={'__init__.py','policy.json','worker_nodes/__init__.py','worker_nodes/comfy-env.toml'}:
        raise ValueError('Unexpected KJ adapter assets')
    for name in set(assets)|{'_upstream_init.py','_comfyctl_adapter_identity.json'}:
        path=destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unsafe KJ adapter output')
        if name!='__init__.py' and path.exists():raise ValueError('Refusing existing KJ adapter output: '+name)
    (destination/'_upstream_init.py').write_bytes(originals['__init__.py'])
    for name,data in assets.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    identity={'upstream_commit':source['commit'],'original_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in originals.items()},'adapter_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in assets.items()}}
    (destination/'_comfyctl_adapter_identity.json').write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n')
    return identity
