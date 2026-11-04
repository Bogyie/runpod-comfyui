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
    parser.add_argument('--update-gc', action='store_true', help='Also exercise version updates, disabled-state preservation and generation cleanup')
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
            if args.update_gc:
                def revision(filename, multiplier, broken=False):
                    stream=io.BytesIO()
                    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as original, tarfile.open(fileobj=stream,mode='w:gz') as updated:
                        for member in original:
                            content=original.extractfile(member).read()
                            if member.name.endswith('/nodes/__init__.py') or (not args.native and member.name=='fixture/__init__.py'):
                                content=content.replace(b'np.array(value) * 2', ('np.array(value) * '+str(multiplier)).encode())
                                if broken:
                                    content=content.replace(b'        import numpy as np', b'        raise RuntimeError("injected update failure")\n        import numpy as np')
                            member.size=len(content)
                            updated.addfile(member,io.BytesIO(content))
                    payload=stream.getvalue();(fixture/filename).write_bytes(payload)
                    return hashlib.sha256(payload).hexdigest()

                def update(filename, sha, commit, expected=0):
                    command=['node','update','fixture','--commit',commit,'--archive','/opt/node-fixture/'+filename,
                             '--archive-sha256',sha,'--required-node','ComfyctlAddedEnvironment',
                             '--smoke-workflow','/opt/node-fixture/smoke.json','--skip-hooks','--defer']
                    if not args.auto_lock:command+=['--lock','/opt/locks/host.txt']
                    if expected:
                        process=subprocess.run(['docker','exec',container,'comfyctl',*command],capture_output=True,text=True,timeout=600)
                        assert process.returncode==expected and 'smoke workflow failed' in process.stderr
                        return
                    return cli(container,*command)

                updated=update('v2.tar.gz',revision('v2.tar.gz',3),'e'*40)
                update_generation=updated['selection']['desired']
                assert json.loads(execute(base,graph,180)['outputs']['2']['text'][0])['value']==14
                cli(container,'env','apply','--restart')
                v2=json.loads(execute(base,graph,180)['outputs']['2']['text'][0])
                assert v2['value']==21 and v2['prefix']!=prefix
                cli(container,'env','rollback','--restart')
                assert json.loads(execute(base,graph,180)['outputs']['2']['text'][0])['value']==14
                cli(container,'env','rollback','--restart')
                assert json.loads(execute(base,graph,180)['outputs']['2']['text'][0])['value']==21
                selection=cli(container,'env','status')['generation']['desired']
                update('broken.tar.gz',revision('broken.tar.gz',5,broken=True),'d'*40,expected=1)
                assert cli(container,'env','status')['generation']['desired']==selection
                assert json.loads(execute(base,graph,180)['outputs']['2']['text'][0])['value']==21
                cli(container,'node','disable','fixture','--restart')
                disabled_update=update('v3.tar.gz',revision('v3.tar.gz',4),'c'*40)
                assert 'ComfyctlAddedEnvironment' not in request(base,'/object_info')
                cli(container,'env','apply','--restart')
                assert 'ComfyctlAddedEnvironment' not in request(base,'/object_info')
                cli(container,'node','enable','fixture','--restart')
                v3=json.loads(execute(base,graph,180)['outputs']['2']['text'][0])
                assert v3['value']==28 and v3['prefix']!=v2['prefix']
                before_gc=cli(container,'env','gc','--min-age-hours','0')
                owner=Path(v3['prefix']).parents[1].name
                assert owner in before_gc['retained'] and before_gc['candidates'] and not before_gc['applied']
                removed=cli(container,'env','gc','--apply','--min-age-hours','0')
                assert removed['removed'] and owner not in removed['removed']
                assert json.loads(execute(base,graph,180)['outputs']['2']['text'][0])['value']==28
                prefix=v3['prefix']
                result['update_gc']={'v2':v2,'v3':v3,'disabled_update_generation':disabled_update['selection']['desired'],
                    'update_generation':update_generation,'failed_update_selection_unchanged':True,
                    'code_environment_rollback':'passed','disabled_state_preserved':True,'cleanup':removed}
                print('Version updates, failed update, disabled update and transitive GC passed',flush=True)
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
