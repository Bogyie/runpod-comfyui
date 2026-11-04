#!/usr/bin/env python3
"""Prepare a reviewed ComfyUI-only update while keeping GPU and node pins fixed."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

from snapshot_upstreams import ROOT, digest, resolve, reproduce
from audit_upstreams import audit
from prepare_lock_inputs import prepare as prepare_host
from prepare_workers import prepare as prepare_workers

sys.path.insert(0,str(ROOT/'tools'))
from comfyctl.candidate_env import frozen_pins, verify_gpu_pins


def wheel_payload(data):
    """Ignore resolver comments, preserve versions and every allowed artifact hash."""
    pins=frozen_pins(data)
    result={};logical=''
    for raw in data.decode().splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or line.startswith('--index-url '):continue
        logical+=' '+line.removesuffix('\\').strip()
        if line.endswith('\\'):continue
        name=re.sub(r'[-_.]+','-',logical.strip().split('==',1)[0]).lower()
        result[name]={'version':pins[name],'hashes':sorted(re.findall(r'--hash=sha256:([0-9a-f]{64})',logical))}
        logical=''
    return result


def compile_lock(source,previous,destination,stack,gpu_lock):
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(previous,destination)
    command=['uv','--no-config','pip','compile',str(source),'--python-version',stack['python'],
        '--python-platform',stack['resolver']['python_platform'],'--torch-backend',stack['gpu']['torch_backend'],
        '--only-binary',':all:','--generate-hashes','--emit-index-url','--index-url','https://pypi.org/simple',
        '--no-header','--no-annotate','--constraint',str(gpu_lock),'--output-file',str(destination)]
    # Existing output pins are preferences; only requirements that actually
    # changed may move. GPU constraints are mandatory, not preferences.
    subprocess.run(command,check=True)
    data=destination.read_bytes()
    verify_gpu_pins(frozen_pins(data),frozen_pins(gpu_lock.read_bytes()))
    if wheel_payload(data)==wheel_payload(previous.read_bytes()):
        shutil.copyfile(previous,destination)
        return False
    return True


def prepare_update(root,source_lock,entry,cache,staging,stack):
    candidate=json.loads(json.dumps(source_lock))
    candidate['sources']['comfyui']=entry
    for name,item in candidate['sources'].items():
        directory=cache/name/item['commit']
        if not all((directory/path).is_file() for path in item['files']):
            reproduce(name,item,cache)
    inspected=audit(candidate,cache)
    if inspected['missing_node_sources']:raise ValueError('Update introduced unpinned node sources')
    inputs=staging/'inputs'
    prepare_host(stack,candidate,cache,inputs)
    workers=prepare_workers(stack,candidate,cache,inputs/'workers')
    old_manifest=json.loads((root/'locks/workers/manifest.json').read_text())
    gpu=root/'locks/gpu/linux-amd64-cu128.txt'
    host_changed=compile_lock(inputs/'host.in',root/'locks/host/linux-amd64-cu128.txt',staging/'host.txt',stack,gpu)
    host_pins=frozen_pins((staging/'host.txt').read_bytes())
    if host_pins.get('comfy-env')!=stack['isolation']['version'] or host_pins.get('uv')!=stack['resolver']['uv']:
        raise ValueError('ComfyUI update changed a protected isolation/installer pin')
    worker_changes={}
    for name,definition in workers['workers'].items():
        old=old_manifest['workers'][name]
        filename=old['lock_file']
        output=staging/'workers'/filename
        output.parent.mkdir(exist_ok=True)
        if definition['requirements_sha256']==old['requirements_sha256']:
            shutil.copyfile(root/'locks/workers'/filename,output)
            changed=False
        else:
            changed=compile_lock(inputs/'workers'/(name+'.in'),root/'locks/workers'/filename,output,stack,gpu)
        definition.update(lock_file=filename,lock_sha256=digest(output.read_bytes()))
        worker_changes[name]=changed
    workers['gpu_lock_sha256']=digest(gpu.read_bytes())
    files={'locks/upstreams.lock.json':(json.dumps(candidate,indent=2,sort_keys=True)+'\n').encode(),
           'build/upstream-audit.json':(json.dumps(inspected,indent=2,sort_keys=True)+'\n').encode(),
           'locks/host/linux-amd64-cu128.txt':(staging/'host.txt').read_bytes(),
           'locks/workers/manifest.json':(json.dumps(workers,indent=2,sort_keys=True)+'\n').encode()}
    for path in inputs.rglob('*'):
        if path.is_file():files['build/inputs/'+path.relative_to(inputs).as_posix()]=path.read_bytes()
    for path in (staging/'workers').iterdir():files['locks/workers/'+path.name]=path.read_bytes()
    return files,{'host_lock_changed':host_changed,'worker_locks_changed':worker_changes,
                  'gpu_lock_sha256':digest(gpu.read_bytes()),'gpu_stack_changed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='latest-release',help='Stable release by default; an explicit ref is a review candidate only')
    parser.add_argument('--apply',action='store_true',help='Stage all locks successfully before writing tracked files')
    parser.add_argument('--output',type=Path,default=ROOT/'.work/comfy-update-report.json')
    args=parser.parse_args()
    source_lock=json.loads((ROOT/'locks/upstreams.lock.json').read_text())
    original=source_lock['sources']['comfyui']
    _,entry=resolve('comfyui',{'repository':original['repository'],'role':original['role'],'ref':args.ref},ROOT/'.work/upstreams')
    changed=entry['commit']!=original['commit']
    report={'changed':changed,'applied':False,'from_commit':original['commit'],'to_commit':entry['commit'],
            'resolved_ref':entry['resolved_ref'],'node_pins_changed':False,'gpu_stack_changed':False,
            'scope':'Update preparation only; CPU/GPU gates and digest promotion remain required'}
    if changed and args.apply:
        work=ROOT/'.work';work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='comfy-update-',dir=work) as temporary:
            files,details=prepare_update(ROOT,source_lock,entry,ROOT/'.work/upstreams',Path(temporary),
                                          yaml.safe_load((ROOT/'build/stack.yaml').read_text()))
            changed_files={relative:data for relative,data in files.items()
                           if not (ROOT/relative).is_file() or (ROOT/relative).read_bytes()!=data}
            for relative,data in changed_files.items():
                path=ROOT/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                pending=path.with_name('.'+path.name+'.update')
                pending.write_bytes(data);pending.replace(path)
            report.update(details,applied=True,files_changed=sorted(changed_files))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
