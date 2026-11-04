#!/usr/bin/env python3
"""Install a real stateless node into a new worker, then restart/disable/rollback."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import uuid

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, cli, inside
from probe_workers import execute, FINGERPRINT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--native', action='store_true', help='Exercise upstream register_nodes/configuration instead of the generic adapter')
    parser.add_argument('--auto-lock', action='store_true', help='Resolve node dependencies instead of passing the image lock')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = ROOT/'tests/evidence'/('node-install-native-cpu.json' if args.native else 'node-install-cpu.json')
    args.output.unlink(missing_ok=True)
    image_id = json.loads(docker('image', 'inspect', args.image))[0]['Id']
    token = uuid.uuid4().hex[:10]
    volume = 'comfy-node-install-' + token
    docker('volume', 'create', volume)
    containers = []
    result = {'kind':'added-node-managed-worker-cpu-gate', 'image_id':image_id,
              'mode':'native' if args.native else 'adapter',
              'scope':'Offline asserted fixture source, real frozen wheel installation, CPU node execution and lifecycle; no public repo/Manager/GPU/network-volume certification'}
    with tempfile.TemporaryDirectory(prefix='node-install-fixture-') as temporary:
        fixture = Path(temporary)
        source = (ROOT/'tests/fixtures/added-node/__init__.py').read_bytes()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            files = [('prestartup_script.py', b'raise RuntimeError("Skipped hook must not execute")\n'),
                     ('install.py', b'raise RuntimeError("Install hook must not execute")\n')]
            files += [('__init__.py', b'from comfy_env import register_nodes\nNODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = register_nodes()\n'),
                      ('nodes/__init__.py', source), ('nodes/comfy-env.toml', b'[pypi-dependencies]\nnumpy="*"\n')] if args.native else [('__init__.py', source)]
            for path, data in files:
                member = tarfile.TarInfo('fixture/' + path)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        data = stream.getvalue()
        (fixture/'node.tar.gz').write_bytes(data)
        graph = {'1':{'class_type':'ComfyctlAddedEnvironment','inputs':{'value':7}},
                 '2':{'class_type':'PreviewAny','inputs':{'source':['1',0]}}}
        (fixture/'smoke.json').write_text(json.dumps(graph))

        def launch(suffix):
            container = docker('run','--detach','--platform','linux/amd64','--name',volume+suffix,
                               '--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m',
                               '--mount','type=volume,source='+volume+',target=/workspace',
                               '--mount','type=bind,source='+str(fixture)+',target=/opt/node-fixture,readonly',
                               '--publish','127.0.0.1::8188',args.image,'--cpu','--use-pytorch-cross-attention','--listen','0.0.0.0','--port','8188')
            containers.append(container)
            state = await_ready(container, 300)
            port = json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
            return container,state,'http://127.0.0.1:'+port

        try:
            container,state,base = launch('-base')
            fingerprint = inside(container,FINGERPRINT)
            command = ['node','add','fixtures/added-node','--name','fixture','--commit','f'*40,'--archive','/opt/node-fixture/node.tar.gz',
                       '--archive-sha256',hashlib.sha256(data).hexdigest(),
                       '--required-node','ComfyctlAddedEnvironment','--smoke-workflow','/opt/node-fixture/smoke.json','--defer']
            if not args.auto_lock:command += ['--lock','/opt/locks/host.txt']
            denied = subprocess.run(['docker','exec',container,'comfyctl',*command],capture_output=True,text=True)
            assert denied.returncode==1 and '--skip-hooks' in denied.stderr
            added = cli(container,*command,'--skip-hooks')
            print('Candidate installation and workflow validation passed', flush=True)
            generation = added['selection']['desired']
            assert generation!='image-base' and 'ComfyctlAddedEnvironment' not in request(base,'/object_info')
            docker('stop','--time','25',container)
            container,state,base = launch('-added')
            assert state['generation_id']==generation
            entry = execute(base,graph,180)
            value = json.loads(entry['outputs']['2']['text'][0])
            print('Added node executed after container restart', flush=True)
            assert value['value']==14 and value['uid']==1000 and value['prefix'].startswith('/workspace/runtime/generations/')
            prefix = value['prefix']
            assert value['pid']!=state['child_pid']
            assert inside(container,FINGERPRINT)==fingerprint
            status = cli(container,'env','doctor')
            assert status['ok'] and ('added:fixture-nodes' if args.native else 'added:fixture-managedworker') in status['environments']
            disabled = cli(container,'node','disable','fixture','--restart')
            assert disabled['live_transition']=='committed' and 'ComfyctlAddedEnvironment' not in request(base,'/object_info')
            restored = cli(container,'env','rollback','--restart')
            print('Disable and rollback completed', flush=True)
            assert restored['live_transition']=='committed'
            after = json.loads(execute(base,graph,180)['outputs']['2']['text'][0])
            assert after['value']==14 and after['prefix']==prefix and after['pid']!=value['pid']
            # Drift in a private CPU file must invalidate the managed generation.
            docker('exec',container,'python','-c',"from pathlib import Path;p=Path("+repr(prefix+'/lib/python3.11/site-packages/numpy/__init__.py')+");p.write_text(p.read_text()+'\\n# injected drift\\n')")
            report = cli(container,'env','doctor',expected=2)
            assert 'active-generation-drift' in report['problems']
            reset = cli(container,'env','reset','--restart')
            assert reset['live_transition']=='committed' and 'ComfyctlAddedEnvironment' not in request(base,'/object_info')
            result.update(status='passed', installed_generation=generation, worker=value, restored_worker=after,
                          skipped_hooks='rejected-without-opt-in-and-never-executed', deferred_active_unchanged=True,
                          doctor_includes_added_prefix=True, disable_and_rollback='passed', cpu_file_drift='detected',
                          image_reset='passed', image_package_fingerprint_unchanged=inside(container,FINGERPRINT)==fingerprint)
        except Exception:
            logs=[]
            for container in containers:
                process=subprocess.run(['docker','logs',container],capture_output=True,text=True)
                logs.append(process.stdout[-14000:]+process.stderr[-6000:])
                process=subprocess.run(['docker','exec',container,'sh','-c','cat /workspace/runtime/generations/*/validation.log /workspace/runtime/generations/*/environment-*/install.log'],capture_output=True,text=True)
                logs.append(process.stdout[-24000:]+process.stderr[-2000:])
            (ROOT/'.work/node-install-failure.log').write_text('\n'.join(logs))
            raise
        finally:
            for container in containers:
                docker('rm','--force',container)
            docker('volume','rm',volume)
    result['containers_and_volume_removed']=True
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','image_id':image_id}))


if __name__=='__main__':
    main()
