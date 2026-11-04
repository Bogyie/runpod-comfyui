#!/usr/bin/env python3
"""Verify live file/model schemas, validation/cache callbacks and independent IPC."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, inside
from probe_workers import execute, FINGERPRINT

PROCESSES="""import json,psutil
print(json.dumps([{'pid':p.pid,'python':p.cmdline()[0],'root':p.environ().get('COMFYCTL_METADATA_PACKAGE_ROOT'),
'cpu':p.environ().get('COMFY_CPU'),'cuda_visible_devices':p.environ().get('CUDA_VISIBLE_DEVICES'),'uid':p.uids().effective,
'rss_bytes':p.memory_info().rss,'pss_bytes':p.memory_full_info().pss}
for p in psutil.Process(1).children(recursive=True) if any('persistent_worker.py' in arg for arg in p.cmdline())
and p.environ().get('COMFYCTL_METADATA_WORKER')=='1']))"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/dynamic-metadata-cpu.json')
    args=parser.parse_args();args.output.unlink(missing_ok=True)
    image_id=json.loads(docker('image','inspect',args.image))[0]['Id']
    token=uuid.uuid4().hex[:10];volume='comfy-metadata-'+token
    docker('volume','create',volume);container=None
    result={'kind':'live-metadata-cpu-gate','image_id':image_id,
            'cache_backend':'classic',
            'scope':'Real SDK/private CPU processes and DA3 model choices; no model weights or GPU inference certification'}
    plugin='/opt/probe/ComfyUI/custom_nodes/MetadataGate'
    fixture=ROOT/'tests/fixtures/metadata-probe'
    try:
        container=docker('run','--detach','--platform','linux/amd64','--name',volume,'--read-only',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m',
            '--mount','type=volume,source='+volume+',target=/workspace',
            '--mount','type=bind,source='+str(fixture)+',target='+plugin+',readonly',
            '--publish','127.0.0.1::8188',args.image,'--cpu','--cache-classic','--use-pytorch-cross-attention','--listen','0.0.0.0','--port','8188')
        await_ready(container,400)
        port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort'];base='http://127.0.0.1:'+port
        fingerprint=inside(container,FINGERPRINT)
        def write(relative,value):
            inside(container,'import json;from pathlib import Path;p=Path("/workspace/storage")/'+repr(relative)+';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('+repr(value)+');print(json.dumps(True))')
        def schema(timeout=10):
            with urllib.request.urlopen(base+'/object_info/MetadataFixture',timeout=timeout) as response:
                return json.load(response)['MetadataFixture']['input']['required']['file'][0]
        assert schema()==['none']
        write('input/live.txt','first');assert 'live.txt' in schema()
        def model_choices():
            info=request(base,'/object_info/DownloadAndLoadDepthAnythingV3Model')['DownloadAndLoadDepthAnythingV3Model']['input']['required']['model']
            return info[1]['options'] if info[0]=='COMBO' else info[0]
        before=model_choices()
        assert 'metadata-gate.safetensors' not in before
        write('models/depthanything3/metadata-gate.safetensors','listing-only-not-model-weights')
        after=model_choices()
        assert 'metadata-gate.safetensors' in after, {'before':before,'after':after}
        graph={'1':{'class_type':'MetadataFixture','inputs':{'file':'live.txt','delay':0}},
               '2':{'class_type':'PreviewAny','inputs':{'source':['1',0]}}}
        def run():return json.loads(execute(base,graph,180)['outputs']['2']['text'][0])
        first=run();cached=run();assert first==cached and first['count']==1, {'first':first,'cached':cached}
        write('input/live.txt','second');changed=run();assert changed['count']==2 and changed['text']=='second'
        write('input/reject.txt','reject')
        rejected={'1':{'class_type':'MetadataFixture','inputs':{'file':'reject.txt','delay':0}},'2':graph['2']}
        try:request(base,'/prompt',{'prompt':rejected})
        except urllib.error.HTTPError as error:
            assert error.code==400 and 'fixture rejected' in error.read().decode()
        else:raise AssertionError('VALIDATE_INPUTS rejection was lost')
        graph['1']['inputs']['delay']=12
        write('input/live.txt','busy')
        submitted=request(base,'/prompt',{'prompt':graph})['prompt_id']
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            counter=inside(container,'import json;from pathlib import Path;print(json.dumps(Path("/workspace/storage/user/metadata-compute-started").read_text()))')
            if counter=='3':break
            time.sleep(0.1)
        assert counter=='3'
        write('input/while-busy.txt','listed-during-compute')
        start=time.monotonic();assert 'while-busy.txt' in schema();latency=time.monotonic()-start
        assert latency<3 and request(base,'/queue')['queue_running']
        while time.monotonic()<deadline+30:
            history=request(base,'/history/'+submitted)
            if submitted in history:
                assert history[submitted]['status']['status_str']=='success';break
            time.sleep(0.2)
        else:raise AssertionError('Busy compute did not finish')
        workers=inside(container,PROCESSES);assert len(workers)==6
        assert all(row['cpu']=='1' and row['cuda_visible_devices']=='' and row['uid']==1000 and row['python'].startswith('/opt/workers/') for row in workers)
        victim=next(row for row in workers if row['root']==plugin)
        docker('exec','--user','1000:1000',container,'python','-c','import os,signal;os.kill('+str(victim['pid'])+',signal.SIGKILL)')
        recovery_start=time.monotonic()
        assert 'while-busy.txt' in schema(timeout=90)
        restarted=next(row for row in inside(container,PROCESSES) if row['root']==plugin)
        assert restarted['pid']!=victim['pid']
        recovery_seconds=time.monotonic()-recovery_start
        graph['1']['inputs']['delay']=0
        recovered_compute=run()
        assert recovered_compute['pid']==changed['pid'] and recovered_compute['text']=='busy'
        write('user/metadata-slow','slow')
        failures=[]
        def slow_request():
            try:schema(timeout=90)
            except Exception as error:failures.append(type(error).__name__)
        thread=threading.Thread(target=slow_request,daemon=True);thread.start()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            started=inside(container,'import json;from pathlib import Path;print(json.dumps(Path("/workspace/storage/user/metadata-rpc-started").exists()))')
            if started:break
            time.sleep(0.1)
        assert started
        docker('exec','--user','1000:1000',container,'python','-c','import os,signal;os.kill('+str(restarted['pid'])+',signal.SIGKILL)')
        thread.join(timeout=30);assert not thread.is_alive() and failures
        inside(container,'import json;from pathlib import Path;Path("/workspace/storage/user/metadata-slow").unlink();print(json.dumps(True))')
        assert 'while-busy.txt' in schema(timeout=90)
        after_mid_call=next(row for row in inside(container,PROCESSES) if row['root']==plugin)
        assert after_mid_call['pid']!=restarted['pid']
        assert run()['pid']==changed['pid']
        write('input/live.txt','always-change')
        nan_first=run();nan_second=run()
        assert nan_second['count']==nan_first['count']+1 and nan_first['pid']==nan_second['pid']==changed['pid']
        assert inside(container,FINGERPRINT)==fingerprint
        result.update(status='passed',input_list_updated=True,da3_local_model_list_updated=True,
            is_changed={'first':first,'cached':cached,'changed':changed},validate_inputs='real-rejection-and-input_types-signature-forwarded',
            metadata_while_compute_running_seconds=latency,cpu_metadata_workers=workers,metadata_worker_kill_recovery=restarted,
            metadata_recovery_seconds=recovery_seconds,compute_preserved_after_metadata_kill=recovered_compute,
            mid_call_metadata_crash={'request_failed_explicitly':failures,'replacement_worker':after_mid_call,'compute_pid_preserved':True},
            is_changed_nan_always_invalidates={'first':nan_first,'second':nan_second},
            image_package_fingerprint_unchanged=True)
        docker('stop','--time','25',container)
        assert json.loads(docker('inspect',container))[0]['State']['ExitCode']==0
    except Exception:
        if container:
            logs=subprocess.run(['docker','logs',container],capture_output=True,text=True)
            details=docker('inspect','--format','{{json .State}}',container)
            memory=subprocess.run(['docker','exec','--user','1000:1000',container,'cat','/sys/fs/cgroup/memory.events'],capture_output=True,text=True)
            (ROOT/'.work/metadata-gate-failure.log').write_text((logs.stdout+logs.stderr)[-36000:]+'\nSTATE\n'+details+'\nMEMORY\n'+memory.stdout+memory.stderr)
        raise
    finally:
        if container:docker('rm','--force',container)
        docker('volume','rm',volume)
    result['container_and_volume_removed']=True
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':'passed','image_id':image_id}))


if __name__=='__main__':main()
