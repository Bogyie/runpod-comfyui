#!/usr/bin/env python3
"""Apply the reviewed mixed-isolation adapter to hash-checked iTools source."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST_NODES = {
    'iToolsKSampler': {'module':'ksampler', 'class':'IToolsKSampler', 'display_name':'KSampler',
                      'reason':'Calls host common_ksampler with live MODEL/conditioning objects'},
    'iToolsVaePreview': {'module':'vae_preview', 'class':'IToolsVaePreview', 'display_name':'Preview Bridge ⛳',
                        'reason':'Calls decode on the host VAE object and returns preview UI'},
}
DATA_HELPERS = '''
# runpod-comfyui: mutable iTools files live with user data, not node source.
def paint_directory():
    root = os.environ.get("COMFYCTL_ITOOLS_DATA") or os.path.join(folder_paths.get_user_directory(), "comfyctl", "itools")
    if not os.path.isabs(root):
        raise RuntimeError("iTools data directory must be absolute")
    path = os.path.join(root, "paint")
    os.makedirs(path, exist_ok=True)
    return path


def default_prompts_path():
    from pathlib import Path
    path = Path(paint_directory()).parent / "prompts.txt"
    try:
        with path.open("xb") as output:
            output.write((Path(project_dir) / "examples" / "prompts.txt").read_bytes())
    except FileExistsError:
        pass
    return str(path)
'''


def apply(destination: Path, source: dict, adapter: Path) -> dict:
    if source['commit'] != 'a8f2fef227ca5b0cb9321c39ac7b874a906b1a5b':
        raise ValueError('Unreviewed iTools revision')
    names = ['__init__.py', 'iTools_nodes.py', 'backend/shared.py', 'backend/iserver.py',
             'backend/prompter.py', 'backend/prompter_multi.py', 'nodes/prompt_loader.py',
             'nodes/prompt_saver.py', 'nodes/experimental/paint_node.py']
    originals = {}
    for name in names:
        path = destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unsafe adapter source path')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['files'].get(name):
            raise ValueError(f'Refusing to patch unknown iTools source: {name}')
        originals[name] = raw.decode()
    tree = ast.parse(originals['iTools_nodes.py'])
    catalog = next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NODE_CLASS_MAPPINGS' for t in n.targets))
    node_ids = [ast.literal_eval(k) for k in catalog.keys]
    if len(node_ids) != 22 or not set(HOST_NODES).issubset(node_ids):
        raise ValueError('Unexpected iTools catalog')
    patched = {}
    for name in ['backend/iserver.py','backend/prompter.py','backend/prompter_multi.py']:
        text = originals[name]
        anchor = '@PromptServer.instance.routes.'
        if text.count(anchor) != (7 if name.endswith('iserver.py') else 1):
            raise ValueError('iTools HTTP route layout changed')
        before, after = text.split(anchor,1)
        # Preserve actual host routes; worker import records no host endpoints.
        text = before + '_comfyctl_routes = web.RouteTableDef() if os.environ.get("COMFYCTL_ITOOLS_WORKER") == "1" else PromptServer.instance.routes\n\n' + anchor + after
        import_anchor = 'from server import PromptServer'
        if text.count(import_anchor) != 1:
            raise ValueError('iTools server import layout changed')
        text = text.replace(import_anchor, 'import os as _comfyctl_os\nif _comfyctl_os.environ.get("COMFYCTL_ITOOLS_WORKER") != "1":\n    from server import PromptServer')
        patched[name] = text.replace(anchor,'@_comfyctl_routes.')
    patched['backend/shared.py'] = originals['backend/shared.py'] + DATA_HELPERS
    anchor = 'os.path.join(project_dir, "backend")'
    for name in ['backend/iserver.py','nodes/experimental/paint_node.py']:
        text = patched.get(name, originals[name])
        if text.count(anchor) != (4 if name.endswith('iserver.py') else 1):
            raise ValueError('iTools Paint path layout changed')
        if name.endswith('iserver.py'):
            text = text.replace('from .shared import project_dir, styles, get_safe_path',
                                'from .shared import project_dir, styles, get_safe_path, paint_directory')
        else:
            text = text.replace('    project_dir,', '    project_dir,\n    paint_directory,')
        patched[name] = text.replace(anchor,'paint_directory()')
    for name in ['nodes/prompt_loader.py','nodes/prompt_saver.py']:
        text = originals[name]
        anchor = 'os.path.join(project_dir, "examples", "prompts.txt")'
        if text.count(anchor) != 1:
            raise ValueError('iTools prompt path layout changed')
        patched[name] = text.replace('from ..backend.shared import FileHandler, project_dir',
                                    'from ..backend.shared import FileHandler, project_dir, default_prompts_path').replace(anchor,'default_prompts_path()')
    # Finish all validation before changing any source file.
    copied = {}
    for path in sorted(adapter.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        relative = path.relative_to(adapter).as_posix()
        copied[relative] = path.read_bytes()
    if set(copied) != {'__init__.py','_comfyctl_adapter.py','worker_nodes/__init__.py','worker_nodes/comfy-env.toml'}:
        raise ValueError('Unexpected iTools adapter assets')
    generated = set(copied) | {'_upstream_init.py','_comfyctl_policy.json','_comfyctl_adapter_identity.json'}
    for name in generated:
        path = destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unsafe adapter output path')
        if name != '__init__.py' and path.exists():
            raise ValueError(f'Refusing to overwrite existing adapter output: {name}')
    (destination/'_upstream_init.py').write_text(originals['__init__.py'])
    for name,text in patched.items():
        (destination/name).write_text(text)
    for name,data in copied.items():
        path = destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    policy = {'schema_version':1,'source_commit':source['commit'],'base_node_ids':node_ids,
              'host_nodes':HOST_NODES,'scope':'Candidate mixed isolation; representative API/UI and model-object tests required'}
    (destination/'_comfyctl_policy.json').write_text(json.dumps(policy,indent=2,sort_keys=True)+'\n')
    identity = {'upstream_commit':source['commit'], 'original_hashes':{n:source['files'][n] for n in names},
                'adapter_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in copied.items()},
                'patched_hashes':{n:hashlib.sha256(v.encode()).hexdigest() for n,v in patched.items()}}
    (destination/'_comfyctl_adapter_identity.json').write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n')
    return identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    lock=json.loads((ROOT/'locks/upstreams.lock.json').read_text())
    apply(args.destination,lock['sources']['itools'],ROOT/'build/adapters/itools')


if __name__ == '__main__':
    main()
