#!/usr/bin/env python3
"""Exercise KJ native-worker image/mask/bbox IPC and preserved host preview.

Uses only an owned CPU test container and removes it before writing success.
Model checkpoint inference and browser UI interaction are separate gates.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from probe_host import ROOT,docker,request
from probe_workers import execute,FINGERPRINT,ENVIRONMENT,PROCESSES
from probe_itools import image_result


def processes(container):
    rows=json.loads(docker('exec',container,'python','-c',PROCESSES))
    found=[p for p in rows if p['cmd'][0]=='/opt/workers/kjnodes-workernodes/bin/python']
    if len(found)!=1 or found[0]['cpu_mode']!='1' or found[0]['attention_policy']!='pytorch':
        raise RuntimeError('Missing or incorrect KJ worker process')
    return found[0]


def suite(container,base,timeout):
    policy=json.loads((ROOT/'build/adapters/kjnodes/policy.json').read_text())
    objects=request(base,'/object_info')
    if not set(policy['worker_nodes']).issubset(objects):raise RuntimeError('KJ worker nodes missing')
    before=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
    environment=json.loads(docker('exec',container,'/opt/workers/kjnodes-workernodes/bin/python','-c',ENVIRONMENT,'color_matcher'))
    if environment['prefix']!='/opt/workers/kjnodes-workernodes' or not environment['extra_realpath'].startswith('/opt/workers/kjnodes-workernodes/') or any(p.startswith('/opt/runtime/venv/') for p in environment['sys_path']):
        raise RuntimeError('KJ dependencies leaked from host')
    graph={'1':{'class_type':'EmptyImage','inputs':{'width':64,'height':32,'batch_size':1,'color':0x202020}},'2':{'class_type':'EmptyImage','inputs':{'width':64,'height':32,'batch_size':1,'color':0xc0c0c0}},'3':{'class_type':'ColorMatchV2','inputs':{'image_target':['1',0],'image_ref':['2',0],'method':'hm','strength':1.0,'multithread':False}},'4':{'class_type':'SaveImage','inputs':{'images':['3',0],'filename_prefix':'kj-color-gate'}}}
    color=image_result(base,execute(base,graph,timeout),'4')
    output='/opt/probe/ComfyUI/output/'+color['image']['filename']
    pixel=json.loads(docker('exec',container,'python','-c',"from PIL import Image;import json,sys;im=Image.open(sys.argv[1]);print(json.dumps(list(im.getpixel((0,0)))))",output))
    if pixel!=[192,192,192]:raise RuntimeError('KJ ColorMatch returned original/fallback pixels')
    original=processes(container)
    graph={'1':{'class_type':'SolidMask','inputs':{'value':0.5,'width':64,'height':32}},'2':{'class_type':'ResizeMask','inputs':{'mask':['1',0],'width':32,'height':16,'keep_proportions':False,'upscale_method':'nearest-exact','crop':'disabled'}},'3':{'class_type':'GetMaskSizeAndCount','inputs':{'mask':['2',0]}},'4':{'class_type':'ComfyctlKJInspectMask','inputs':{'mask':['3',0],'width':['3',1],'height':['3',2],'count':['3',3]}}}
    mask=json.loads(execute(base,graph,timeout)['outputs']['4']['text'][0])
    if mask!={'shape':[1,16,32],'width':32,'height':16,'count':1,'mean':0.5}:raise RuntimeError('KJ mask/scalar IPC differs from expected values')
    def bbox_graph(malformed,offset=0):
        return {'1':{'class_type':'ComfyctlKJBbox','inputs':{'malformed':malformed,'offset':offset}},'2':{'class_type':'BboxToInt','inputs':{'bboxes':['1',0],'index':0}},'3':{'class_type':'ComfyctlKJInspectInts','inputs':{key:['2',i] for i,key in enumerate(['x','y','width','height','cx','cy'])}}}
    bbox=json.loads(execute(base,bbox_graph(False),timeout)['outputs']['3']['text'][0])
    if bbox!={'x':12,'y':8,'width':24,'height':16,'cx':24,'cy':16}:raise RuntimeError('KJ bbox/int IPC changed values')
    error=execute(base,bbox_graph(True),timeout,success=False)
    if processes(container)['pid']!=original['pid']:raise RuntimeError('KJ node exception killed its worker')
    if not any(kind=='execution_error' and item.get('node_type')=='BboxToInt' for kind,item in error['status']['messages']):
        raise RuntimeError('Malformed bbox did not fail in the real KJ node')
    # Different input values require a fresh KJ invocation after the exception.
    recovered_entry=execute(base,bbox_graph(False,offset=1),timeout)
    cached=[node for kind,item in recovered_entry['status']['messages'] if kind=='execution_cached' for node in item.get('nodes',[])]
    if '2' in cached:raise RuntimeError('KJ recovery graph was incorrectly served from cache')
    recovered=json.loads(recovered_entry['outputs']['3']['text'][0])
    if recovered!={**bbox,'x':13,'cx':25} or processes(container)['pid']!=original['pid']:
        raise RuntimeError('KJ worker did not recover after an exception')
    sigma_graph={'1':{'class_type':'ComfyctlKJSigmaFloats','inputs':{}},'2':{'class_type':'FloatToSigmas','inputs':{'float_list':['1',0]}},'3':{'class_type':'VisualizeSigmasKJ','inputs':{'sigmas':['2',0],'start_step':0,'end_step':-1}},'4':{'class_type':'SaveImage','inputs':{'images':['3',1],'filename_prefix':'kj-sigmas-gate'}},'5':{'class_type':'ComfyctlKJInspectSigmas','inputs':{'sigmas':['3',0]}}}
    sigma_entry=execute(base,sigma_graph,timeout)
    plot=image_result(base,sigma_entry,'4')
    if plot['width']<128 or plot['height']<128 or json.loads(sigma_entry['outputs']['5']['text'][0])!=[1.0,0.5,0.0]:
        raise RuntimeError('KJ worker SIGMAS to host matplotlib rendering failed')
    host=json.loads(execute(base,{'1':{'class_type':'ComfyctlKJHostState','inputs':{}}},timeout)['outputs']['1']['text'][0])
    if host['worker_catalog_imported_on_host'] or host['host_has_color_matcher'] or host['host_imported_color_matcher'] or original['pid']==host['host_pid']:
        raise RuntimeError('KJ private compute dependency imported on host')
    for node in ['ColorMatchV2','ResizeMask','BboxToInt']:
        if host['class_modules'][node]!='comfy_env.isolation.metadata':raise RuntimeError('KJ node did not use native proxy')
    if host['class_modules']['FastPreview']=='comfy_env.isolation.metadata' or host['class_modules']['ModelPassThrough']=='comfy_env.isolation.metadata':
        raise RuntimeError('KJ host callback/model exception was isolated')
    websocket=json.loads(docker('exec',container,'python','/gate/kjnodes-websocket.py'))
    if websocket['status']!='passed':raise RuntimeError('KJ host binary preview failed')
    if request(base,'/kjnodes/model_mtimes',{'values':['missing-gate-model.safetensors']})!={}:raise RuntimeError('KJ host model listing route failed')
    extensions=[p for p in request(base,'/extensions') if '/ComfyUI-KJNodes/' in p]
    assets=json.loads(docker('exec',container,'python','-c',"from pathlib import Path;import json;root=Path('custom_nodes/ComfyUI-KJNodes/kjweb_async');print(json.dumps(['/kjweb_async/'+p.relative_to(root).as_posix() for p in root.rglob('*.js')]))"))
    if not extensions or not assets:raise RuntimeError('KJ UI assets missing')
    for path in extensions+assets:
        with urllib.request.urlopen(base+path,timeout=20) as response:
            if response.status!=200 or not response.read():raise RuntimeError('KJ UI script missing')
    after=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
    if before!=after:raise RuntimeError('KJ execution changed host packages')
    return {'kind':'kjnodes-mixed-isolation-cpu-gate','status':'passed','policy':policy,'environment':environment,'color':{**color,'pixel':pixel,'input_pixel':[32,32,32],'fallback_rejected':True},'mask':mask,'bbox':bbox,'node_error_status':error['status'],'node_error_recovery':'passed','worker_sigmas_to_host_plot':plot,'host':host,'worker':original,'websocket':websocket,'ui_extension_count':len(extensions),'async_script_count':len(assets),'host_package_fingerprint':after,'scope':'108 metadata registrations plus representative CPU ColorMatchV2, MASK/BBOX/scalar IPC, real node exception/recovery, worker SIGMAS to host matplotlib, host binary WebSocket and HTTP/assets. Not real model checkpoint inference, GPU, all 108 algorithms or browser interaction.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-worker-probe')
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/kjnodes-cpu-probe.json')
    args=parser.parse_args();args.output.unlink(missing_ok=True)
    fixture=ROOT/'tests/fixtures/kjnodes-probe-nodes'
    websocket=ROOT/'tests/fixtures/kjnodes-websocket.py'
    name='runpod-kj-gate-'+uuid.uuid4().hex[:10]
    container=docker('run','--detach','--platform','linux/amd64','--name',name,'--publish','127.0.0.1::8188','--volume',str(fixture)+':/opt/probe/ComfyUI/custom_nodes/comfyctl_kj_probe:ro','--volume',str(websocket)+':/gate/kjnodes-websocket.py:ro',args.image)
    try:
        port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base='http://127.0.0.1:'+port;end=time.monotonic()+args.timeout
        while True:
            try:request(base,'/system_stats');break
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                state=json.loads(docker('inspect',container))[0]['State']
                if not state['Running'] or time.monotonic()>end:raise RuntimeError('KJ candidate startup failed: '+docker('logs',container))
                time.sleep(1)
        value=suite(container,base,args.timeout)
        value['image_id']=json.loads(docker('image','inspect',args.image))[0]['Id']
    finally:docker('rm','--force',container)
    value['container_removed']=True
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':value['status'],'isolated_nodes':len(value['policy']['worker_nodes']),'websocket':value['websocket']['status']}))


if __name__=='__main__':main()
