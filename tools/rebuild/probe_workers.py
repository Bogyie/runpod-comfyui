#!/usr/bin/env python3
"""Exercise actual SAM3/DA3 comfy-env workers, CPU tensor/UI IPC and recovery.

No model is downloaded: segmentation/depth inference and GPU worker execution
are separate gates. Every container created here is removed, including on error.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import uuid
from pathlib import Path

from probe_host import ROOT, docker, request

FINGERPRINT = '''import hashlib,importlib.metadata,json,pathlib,sysconfig
site=pathlib.Path(sysconfig.get_path('purelib'))
packages=sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions())
files=[site/'torch/__init__.py',site/'torch/version.py',*sorted((site/'torch').glob('_C*.so'))]
print(json.dumps({'packages_sha256':hashlib.sha256(json.dumps(packages).encode()).hexdigest(),
'gpu_files':{str(p.relative_to(site)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}))'''
# Compute worker checks are separate from the CPU metadata worker pool.
PROCESSES = '''import json,psutil
print(json.dumps([{'pid':p.pid,'ppid':p.ppid(),'cmd':p.cmdline(),'attention_policy':p.environ().get('COMFYCTL_WORKER_ATTENTION'),'cpu_mode':p.environ().get('COMFY_CPU')} for p in psutil.Process(1).children(recursive=True) if any('persistent_worker.py' in arg for arg in p.cmdline()) and p.environ().get('COMFYCTL_METADATA_WORKER') != '1']))'''
ENVIRONMENT = '''import importlib.util,json,pathlib,sys,torch
extra=importlib.util.find_spec(sys.argv[1])
print(json.dumps({'prefix':sys.prefix,'sys_path':sys.path,'extra_realpath':str(pathlib.Path(extra.origin).resolve()),
 'torch_version':torch.__version__,'torch_realpath':str(pathlib.Path(torch.__file__).resolve())}))'''


WORKER_IDENTITIES = """import hashlib,json
from pathlib import Path
root=Path('/opt/locks/workers')
manifest=json.loads((root/'manifest.json').read_text())
if manifest['gpu_lock_sha256']!=hashlib.sha256(Path('/opt/locks/gpu.txt').read_bytes()).hexdigest():raise RuntimeError('Final GPU lock identity disagrees')
verified={}
for name,definition in manifest['workers'].items():
    prefix=Path('/opt/workers')/definition['environment']
    if json.loads((prefix/'worker-lock.json').read_text())!=definition:raise RuntimeError('Full worker identity missing: '+name)
    if hashlib.sha256((root/definition['lock_file']).read_bytes()).hexdigest()!=definition['lock_sha256']:raise RuntimeError('Final worker lock disagrees: '+name)
    links=json.loads((prefix/'gpu-links.json').read_text())
    if links['worker_prefix']!=str(prefix) or links['host_site_packages_on_sys_path']:raise RuntimeError('Final worker prefix changed: '+name)
    verified[name]={'full_identity':'matched','lock_sha256':definition['lock_sha256'],'prefix':str(prefix)}
print(json.dumps(verified))
"""


def execute(base: str, graph: dict, timeout: int, success: bool = True) -> dict:
    submitted = request(base,'/prompt',{'prompt':graph})
    if submitted.get('node_errors'):
        raise RuntimeError(f'Graph validation failed: {submitted}')
    pid = submitted['prompt_id']
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        history = request(base,'/history/'+pid)
        if pid in history:
            entry = history[pid]
            if (entry['status']['status_str']=='success') != success:
                raise RuntimeError(f'Unexpected worker graph result: {entry["status"]}')
            return entry
        time.sleep(0.5)
    raise RuntimeError('Worker graph execution timed out')


def points(entry: dict, expected_x: float) -> dict:
    value = ast.literal_eval(entry['outputs']['3']['text'][0])
    if value != {'points':[[expected_x,0.5]],'labels':[1]}:
        raise RuntimeError(f'Worker coordinate result disagrees with input image: {value}')
    image = base64.b64decode(entry['outputs']['2']['bg_image'][0],validate=True)
    if not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9'):
        raise RuntimeError('SAM3 UI response did not contain JPEG data')
    return {'normalized_points':value,'ui_jpeg_sha256':hashlib.sha256(image).hexdigest(),'ui_jpeg_bytes':len(image)}


def worker_processes(container: str) -> dict:
    rows = json.loads(docker('exec',container,'python','-c',PROCESSES))
    workers = {}
    for row in rows:
        python = row['cmd'][0]
        if not python.startswith('/opt/workers/') or row['pid']==1 or row['attention_policy']!='pytorch' or row['cpu_mode']!='1':
            raise RuntimeError(f'Worker did not use an isolated interpreter: {row}')
        workers[Path(python).parent.parent.name] = row
    if set(workers) != {'sam3-nodes','depthanythingv3-nodes'}:
        raise RuntimeError(f'Missing or unexpected persistent worker process: {workers}')
    return workers



def tensor_views(container: str) -> dict:
    source=(ROOT/'tests/fixtures/worker_view_case.py').read_text()
    program = """import json,tempfile,sys,torch
from pathlib import Path
sys.path.insert(0,'/opt/probe/ComfyUI')
from comfy.cli_args import args
args.cpu=True
from comfy_env.isolation.workers.subprocess import SubprocessWorker
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp,'worker_view_case.py').write_text(CASE_SOURCE)
    worker=SubprocessWorker(python=Path('/opt/workers/depthanythingv3-nodes/bin/python'),working_dir=Path('/opt/probe/ComfyUI'),sys_path=[tmp],env={'COMFY_CPU':'1','COMFYCTL_WORKER_ATTENTION':'pytorch'},name='cpu-view-gate',health_check_timeout=30)
    x=torch.arange(60,dtype=torch.float32).reshape(3,4,5)[1:]
    expected={'slice':x[1:],'offset':x[:,:,1:],'transpose':x.transpose(1,2),'broadcast':x[:1].expand(4,-1,-1),'empty_view':x[:0],'owned_empty':x.new_empty((0,4,5))}
    try:
        result=worker.call_method(module_name='worker_view_case',class_name='Views',method_name='run',kwargs={'x':x})
        for name,value in expected.items():
            if not torch.equal(result[name],value):raise RuntimeError('Native CPU view IPC changed values: '+name)
        echo=worker.call_method(module_name='worker_view_case',class_name='Views',method_name='echo',kwargs={'x':torch.empty((0,4,5),dtype=torch.float32)})
        if list(echo.shape)!=[0,4,5] or echo.dtype!=torch.float32 or echo.device.type!='cpu':raise RuntimeError('Empty parent-to-worker CPU tensor changed')
    finally:worker.shutdown()
    if worker.is_alive():raise RuntimeError('CPU view worker remained alive')
    for name,value in expected.items():
        if not torch.equal(result[name],value):raise RuntimeError('CPU view storage expired after shutdown')
    print(json.dumps({'status':'passed','input_storage_offset':x.storage_offset(),'empty_parent_to_worker':'passed','cases':{name:{'shape':list(t.shape),'stride':list(t.stride()),'storage_offset':t.storage_offset()} for name,t in result.items()},'shutdown':'passed'}))
"""
    return json.loads(docker('exec',container,'python','-c','CASE_SOURCE='+repr(source)+'\n'+program).splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-worker-probe')
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/workers-cpu-probe.json')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    image = json.loads(docker('image','inspect',args.image))[0]
    if image['Architecture']!='amd64':
        raise RuntimeError('Expected actual Linux amd64 image')
    name='runpod-worker-gate-'+uuid.uuid4().hex[:10]
    container=docker('run','--detach','--platform','linux/amd64','--name',name,'--publish','127.0.0.1::8188',args.image)
    result=None
    try:
        details=json.loads(docker('inspect',container))[0]
        port=details['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base='http://127.0.0.1:'+port
        start=time.monotonic();deadline=start+args.timeout
        while True:
            try:
                stats=request(base,'/system_stats');break
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                state=json.loads(docker('inspect',container))[0]['State']
                if not state['Running'] or time.monotonic()>deadline:
                    raise RuntimeError('Worker image did not become ready:\n'+docker('logs',container))
                time.sleep(1)
        ready_seconds=time.monotonic()-start
        if any(d['type']!='cpu' for d in stats['devices']):
            raise RuntimeError('This gate must run in explicit CPU mode')
        objects=request(base,'/object_info')
        for node in ['SAM3PointCollector','SAM3CreatePoint','DA3_CreateCameraParams','DepthAnything_V3']:
            if node not in objects:raise RuntimeError(f'Expected isolation node missing: {node}')
        worker_manifest=json.loads(docker('exec',container,'python','-c',"from pathlib import Path;print(Path('/opt/locks/workers/manifest.json').read_text())"))
        identities=json.loads(docker('exec',container,'python','-c',WORKER_IDENTITIES))
        before=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
        sam_graph=json.loads((ROOT/'tests/workflows/sam3-points-cpu.json').read_text())
        da_graph=json.loads((ROOT/'tests/workflows/da3-camera-cpu.json').read_text())
        sam=points(execute(base,sam_graph,args.timeout),0.25)
        da=execute(base,da_graph,args.timeout)
        text=da['outputs']['2']['text'][0]
        matrices=[ast.literal_eval(s) for s in re.findall(r'tensor\((\[[\d\s.,eE+\-\[\]]+\])\)',text)]
        expected=[[[[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]]],
                  [[[[50.,0.,32.],[0.,50.,16.],[0.,0.,1.]]]]]
        if matrices!=expected or "'image_size': [32, 64]" not in text:
            raise RuntimeError(f'DA3 tensors did not survive worker IPC: {text}')
        original=worker_processes(container)
        environments={}
        for env,extra in [('sam3-nodes','ftfy'),('depthanythingv3-nodes','omegaconf')]:
            prefix='/opt/workers/'+env
            info=json.loads(docker('exec',container,prefix+'/bin/python','-c',ENVIRONMENT,extra))
            if info['prefix']!=prefix or not info['extra_realpath'].startswith(prefix+'/'):
                raise RuntimeError(f'Worker dependency escaped its venv: {info}')
            if any(p.startswith('/opt/runtime/venv/') for p in info['sys_path']):
                raise RuntimeError(f'Host site-packages leaked into worker: {info}')
            environments[env]=info
        # A real node exception must reach history without crashing its worker.
        broken=copy.deepcopy(sam_graph)
        broken['2']['inputs']['coordinates']='[{"x":16}]'
        failure=execute(base,broken,args.timeout,success=False)
        after_error=worker_processes(container)
        if after_error['sam3-nodes']['pid']!=original['sam3-nodes']['pid']:
            raise RuntimeError('An ordinary node exception killed the worker')
        # Crash injection: the next uncached call must restart only this worker.
        docker('exec',container,'python','-c',f'import os,signal;os.kill({original["sam3-nodes"]["pid"]},signal.SIGKILL)')
        resumed=copy.deepcopy(sam_graph)
        resumed['2']['inputs']['coordinates']='[{"x":12,"y":32}]'
        sam_after_restart=points(execute(base,resumed,args.timeout),0.1875)
        restarted=worker_processes(container)
        if restarted['sam3-nodes']['pid']==original['sam3-nodes']['pid']:
            raise RuntimeError('Dead worker was not replaced')
        if restarted['depthanythingv3-nodes']['pid']!=original['depthanythingv3-nodes']['pid']:
            raise RuntimeError('Unrelated DA3 worker restarted')
        views=tensor_views(container)
        after=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
        if before!=after:raise RuntimeError('Worker execution changed host package metadata or sampled GPU files')
        result={'kind':'comfy-env-native-workers-cpu-gate','image_id':image['Id'],
                'ready_seconds':round(ready_seconds,3),'worker_manifest':worker_manifest,'worker_identities':identities,'sam3_points_and_ui':sam,'da3_camera_matrices':matrices,
                'worker_environments':environments,'processes_before':original,'processes_after_restart':restarted,
                'cpu_storage_views':views,'ordinary_exception':'propagated-with-worker-alive','error_events':failure['status']['messages'],
                'sam3_after_crash':sam_after_restart,'host_fingerprint_before':before,'host_fingerprint_after':after,
                'scope':'CPU worker registration/tensor/UI IPC, exception and crash recovery only; no segmentation/depth model inference or GPU worker certification'}
    except BaseException:
        print(docker('logs','--tail','100',container))
        raise
    finally:
        subprocess.run(['docker','rm','--force',container],check=False,stdout=subprocess.DEVNULL)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=='__main__':
    main()
