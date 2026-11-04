#!/usr/bin/env python3
"""Apply the hash-guarded VHS tensor-worker boundary without moving queue state."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def apply(destination:Path,source:dict,adapter:Path)->dict:
    if source['commit']!='4d907bee61e92c2e65af3bd6383a4e4d356126d1':raise ValueError('Unreviewed VHS revision')
    originals={}
    for name in ['__init__.py','videohelpersuite/nodes.py','videohelpersuite/image_latent_nodes.py','videohelpersuite/utils.py']:
        path=destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Unsafe VHS source path')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=source['files'].get(name):raise ValueError('Refusing unknown VHS source: '+name)
        originals[name]=data
    text=originals['videohelpersuite/utils.py'].decode()
    anchor='prompt_queue = server.PromptServer.instance.prompt_queue'
    if text.count(anchor)!=1:raise ValueError('VHS queue binding changed')
    text=text.replace(anchor,'prompt_queue = None if os.environ.get("COMFYCTL_VHS_WORKER") == "1" else server.PromptServer.instance.prompt_queue')
    nodes=originals['videohelpersuite/nodes.py'].decode()
    if nodes.count('self.inputs[key][-1]')!=2:raise ValueError('VHS input generator tuple layout changed')
    nodes=nodes.replace('self.inputs[key][-1]','self.inputs[key][0]')
    assets={p.relative_to(adapter).as_posix():p.read_bytes() for p in adapter.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if set(assets)!={'__init__.py','policy.json','worker_nodes/__init__.py','worker_nodes/comfy-env.toml'}:raise ValueError('Unexpected VHS adapter assets')
    policy=json.loads(assets['policy.json'])
    if policy['source_commit']!=source['commit'] or len(policy['worker_nodes'])!=18:raise ValueError('Unexpected VHS policy')
    for name in set(assets)|{'_upstream_init.py','_comfyctl_adapter_identity.json'}:
        path=destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Unsafe VHS adapter output')
        if name!='__init__.py' and path.exists():raise ValueError('Refusing existing VHS adapter output')
    (destination/'_upstream_init.py').write_bytes(originals['__init__.py'])
    (destination/'videohelpersuite/utils.py').write_text(text)
    (destination/'videohelpersuite/nodes.py').write_text(nodes)
    for name,data in assets.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    identity={'upstream_commit':source['commit'],'original_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in originals.items()},'adapter_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in assets.items()},'patched_utils_sha256':hashlib.sha256(text.encode()).hexdigest(),'patched_nodes_sha256':hashlib.sha256(nodes.encode()).hexdigest()}
    (destination/'_comfyctl_adapter_identity.json').write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n')
    return identity
