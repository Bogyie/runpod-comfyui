#!/usr/bin/env python3
"""Test real pinned ComfyUI source/frontend updates and private-worker rebase."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import uuid

import yaml

from build_probe import execution_contract, materialize
from snapshot_upstreams import fetch, digest, inspect_archive
from probe_host import ROOT, docker, request, verify_frontend
from probe_runtime import await_ready, cli, inside, state
from probe_workers import execute


def replace_requirement(lock,name,replacement):
    lines=lock.splitlines(keepends=True)
    result=[];found=False;index=0
    while index<len(lines):
        line=lines[index]
        if line.startswith(name+'=='):
            if found:raise ValueError('Duplicate locked requirement')
            found=True
            while line.rstrip().endswith('\\'):
                index+=1;line=lines[index]
            result.append(replacement)
        else:result.append(line)
        index+=1
    if not found:raise ValueError('Missing locked requirement')
    return ''.join(result)


def updated_image(image,tag,context,containers):
    fixture=json.loads((ROOT/'tests/fixtures/comfy-update.json').read_text())
    data=fetch('https://codeload.github.com/'+fixture['repository']+'/tar.gz/'+fixture['commit'])
    if digest(data)!=fixture['archive_sha256']:raise ValueError('Comfy update archive drift')
    materialize(data,context/'ComfyUI')
    old=docker('create',image);containers.append(old)
    for path,target in [('/opt/runtime/control/identity.json','identity.json'),
                        ('/opt/runtime/control/baseline.json','baseline.json'),('/opt/locks/host.txt','host.txt')]:
        docker('cp',old+':'+path,str(context/target))
    identity=json.loads((context/'identity.json').read_text())
    baseline=json.loads((context/'baseline.json').read_text())
    host=replace_requirement((context/'host.txt').read_text(),'comfyui-frontend-package',fixture['frontend_lock'])
    (context/'host.txt').write_text(host)
    (context/'frontend.txt').write_text(fixture['frontend_lock'])
    sources=json.loads((ROOT/'locks/upstreams.lock.json').read_text())
    source=sources['sources']['comfyui']
    source.update(commit=fixture['commit'],resolved_ref=fixture['commit'],archive_sha256=digest(data),
                  archive_url='https://codeload.github.com/'+fixture['repository']+'/tar.gz/'+fixture['commit'],
                  files=inspect_archive(data))
    definitions=json.loads((ROOT/'locks/workers/manifest.json').read_text())
    baseline.update(host_lock_sha256=digest(host.encode()))
    baseline.update(execution_contract(yaml.safe_load((ROOT/'build/stack.yaml').read_text()),
                                       sources['sources'],definitions,baseline['host_lock_sha256']))
    identity['inputs']['locks/upstreams.lock.json']=digest((json.dumps(sources,indent=2,sort_keys=True)+'\n').encode())
    identity['inputs']['locks/host/linux-amd64-cu128.txt']=baseline['host_lock_sha256']
    identity['runtime_id']=digest(json.dumps(identity['inputs'],sort_keys=True).encode())
    baseline['runtime_id']=identity['runtime_id']
    for name,value in [('identity',identity),('baseline',baseline)]:
        (context/(name+'.json')).write_text(json.dumps(value))
    (context/'Dockerfile').write_text('FROM '+image+'\nCOPY ComfyUI/ /opt/probe/ComfyUI/\n'
        'COPY host.txt /opt/locks/host.txt\nCOPY frontend.txt /tmp/rebase-frontend.txt\n'
        'RUN uv pip install --no-config --python /opt/runtime/venv/bin/python --no-deps --require-hashes -r /tmp/rebase-frontend.txt && '
        'uv pip check --python /opt/runtime/venv/bin/python && rm /tmp/rebase-frontend.txt\n'
        'COPY identity.json baseline.json /opt/runtime/control/\n')
    started=time.monotonic()
    subprocess.run(['docker','build','--platform','linux/amd64','-t',tag,str(context)],check=True)
    return {'comfy_commit':fixture['commit'],'archive_sha256':fixture['archive_sha256'],
            'execution_sha256':source['files']['execution.py'],'compatibility_id':baseline['compatibility_id'],
            'image_id':json.loads(docker('image','inspect',tag))[0]['Id'],
            'build_seconds':round(time.monotonic()-started,3)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/image-rebase-cpu.json')
    args=parser.parse_args()
    args.output.unlink(missing_ok=True)
    image=json.loads(docker('image','inspect',args.image))[0]['Id']
    token=uuid.uuid4().hex[:10]
    volume='comfy-rebase-'+token
    base_tag='comfy-rebase-base:'+token
    updated='comfy-rebase-updated:'+token
    containers=[]
    result={'kind':'comfy-source-update-and-rebase-cpu-gate','image_id':image,
            'scope':'Pinned official post-release ComfyUI source/frontend update, CPU core/node workflows, private-prefix reuse and drift rebuild. No stable release promotion, GPU or network-volume certification.'}
    docker('volume','create',volume);docker('tag',image,base_tag)
    with tempfile.TemporaryDirectory(prefix='comfy-rebase-fixture-') as temporary:
        fixture=Path(temporary)
        context=fixture/'build';context.mkdir()
        graph={'1':{'class_type':'ComfyctlAddedEnvironment','inputs':{'value':7}},
               '2':{'class_type':'PreviewAny','inputs':{'source':['1',0]}}}
        (fixture/'smoke.json').write_text(json.dumps(graph))
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w:gz') as target:
            files={'__init__.py':b'from comfy_env import register_nodes\nNODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = register_nodes()\n',
                   'nodes/__init__.py':(ROOT/'tests/fixtures/added-node/__init__.py').read_bytes(),
                   'nodes/comfy-env.toml':b'[pypi-dependencies]\nnumpy="*"\n'}
            for name,data in files.items():
                member=tarfile.TarInfo('fixture/'+name);member.size=len(data)
                target.addfile(member,io.BytesIO(data))
        source_data=archive.getvalue();(fixture/'node.tar.gz').write_bytes(source_data)

        def launch(tag,suffix,admin=False):
            command=['run','--detach','--platform','linux/amd64','--name','comfy-rebase-'+token+suffix,
                '--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m',
                '--mount','type=volume,source='+volume+',target=/workspace',
                '--mount','type=bind,source='+str(fixture)+',target=/opt/rebase-fixture,readonly']
            command+=['--entrypoint','/bin/sleep',tag,'1800'] if admin else ['--publish','127.0.0.1::8188',tag,
                '--cpu','--use-pytorch-cross-attention','--listen','0.0.0.0','--port','8188']
            container=docker(*command);containers.append(container)
            return container

        def ready(container):
            record=await_ready(container,300)
            port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
            return record,'http://127.0.0.1:'+port

        def stop(container):docker('stop','--time','25',container)

        def value(base):
            result=json.loads(execute(base,graph,180)['outputs']['2']['text'][0])
            assert result['value']==14 and result['uid']==1000
            return result

        def selected_code(container,record):
            return inside(container,"import hashlib,json;from pathlib import Path;p=Path('/workspace/runtime/generations/"+
                record['generation_id']+"/ComfyUI/execution.py');print(json.dumps(hashlib.sha256(p.read_bytes()).hexdigest()))")

        try:
            result['updated_image']=updated_image(base_tag,updated,context,containers)
            a=launch(base_tag,'-old')
            ready(a)
            old_key=inside(a,"from pathlib import Path;print(Path('/opt/runtime/control/baseline.json').read_text())")['compatibility_id']
            cli(a,'node','disable','itools','--defer')
            added=cli(a,'node','add','fixtures/added-node','--name','fixture','--commit','f'*40,
                '--archive','/opt/rebase-fixture/node.tar.gz','--archive-sha256',digest(source_data),
                '--required-node','ComfyctlAddedEnvironment','--smoke-workflow','/opt/rebase-fixture/smoke.json','--defer')
            stop(a)
            a=launch(base_tag,'-old-added');old_record,base=ready(a)
            old_value=value(base);old_code=selected_code(a,old_record)
            assert 'iToolsCheckerBoard' not in request(base,'/object_info')
            inside(a,"import json;from pathlib import Path;Path('/workspace/storage/user/rebase-marker').write_text('preserve');print(json.dumps(True))")
            stop(a)
            b=launch(updated,'-new-recovery')
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                if state(b)['phase']=='recovery-required':break
                time.sleep(1)
            else:raise AssertionError('Updated ComfyUI silently adopted foreign selection')
            rebased=cli(b,'env','rebase','--from-image',old_key,'--defer')
            assert rebased['environments']=={'fixture':'reused-verified-prefix'}
            stop(b)
            b=launch(updated,'-new-rebased');new_record,base=ready(b)
            result['updated_frontend']=verify_frontend(base)
            frontend=inside(b,"import importlib.metadata,json;print(json.dumps(importlib.metadata.version('comfyui-frontend-package')))")
            assert frontend=='1.58.5'
            result['updated_frontend']['package_version']=frontend
            assert value(base)['prefix']==old_value['prefix']
            assert selected_code(b,new_record)==result['updated_image']['execution_sha256']!=old_code
            assert 'iToolsCheckerBoard' not in request(base,'/object_info')
            stop(b)
            a=launch(base_tag,'-old-rollback');record,base=ready(a)
            assert record['generation_id']==old_record['generation_id']
            assert selected_code(a,record)==old_code and value(base)['prefix']==old_value['prefix']
            stop(a)
            print('Actual ComfyUI update, private-prefix reuse and image rollback passed',flush=True)
            admin=launch(updated,'-offline',admin=True)
            # Only our disposable test prefix is altered. Rebase must recover
            # from source without loading this damaged private environment.
            target=old_value['prefix']+'/lib/python3.11/site-packages/numpy/__init__.py'
            code="from pathlib import Path;p=Path("+repr(target)+");backup=Path('/workspace/runtime/control/rebase-private-backup');backup.write_bytes(p.read_bytes());p.write_bytes(p.read_bytes()+b'\\n# injected drift\\n')"
            docker('exec',admin,'python','-c',code)
            rebuilt=cli(admin,'env','rebase','--from-image',old_key,'--defer')
            assert rebuilt['environments']=={'fixture':'rebuilt-private-environment'}
            docker('exec',admin,'python','-c',"from pathlib import Path;Path("+repr(target)+").write_bytes(Path('/workspace/runtime/control/rebase-private-backup').read_bytes())")
            stop(admin)
            b=launch(updated,'-new-rebuilt');record,base=ready(b)
            rebuilt_value=value(base)
            assert rebuilt_value['prefix']!=old_value['prefix']
            assert selected_code(b,record)==result['updated_image']['execution_sha256']
            assert inside(b,"import json;from pathlib import Path;print(json.dumps(Path('/workspace/storage/user/rebase-marker').read_text()))")=='preserve'
            assert 'iToolsCheckerBoard' not in request(base,'/object_info')
            stop(b)
            result.update(source_compatibility_id=old_key,old_generation=added['selection']['desired'],
                reused_generation=rebased['selection']['desired'],rebuilt_generation=rebuilt['selection']['desired'],
                original_prefix=old_value['prefix'],rebuilt_prefix=rebuilt_value['prefix'],
                image_rollback=True,disabled_state_preserved=True,user_data_preserved=True)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
            print(json.dumps(result,indent=2))
        finally:
            for container in reversed(containers):subprocess.run(['docker','rm','--force',container],capture_output=True)
            subprocess.run(['docker','volume','rm',volume],capture_output=True)
            for tag in [updated,base_tag]:subprocess.run(['docker','image','rm',tag],capture_output=True)


if __name__=='__main__':main()
