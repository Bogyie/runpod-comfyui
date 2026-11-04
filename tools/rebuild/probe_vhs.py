#!/usr/bin/env python3
"""VHS tensor worker, H.264/audio/HTTP and real meta-batch queue integration gate."""
from __future__ import annotations
import argparse
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from probe_host import ROOT,docker,request
from probe_workers import execute,FINGERPRINT,PROCESSES,ENVIRONMENT

DECODE='''import av,base64,io,json,numpy as np,sys
source=sys.argv[1]
if source.startswith("base64:"):source=io.BytesIO(base64.b64decode(source[7:]))
container=av.open(source);streams=[s.type for s in container.streams];frames=list(container.decode(video=0)) if "video" in streams else []
result={"streams":streams,"frames":len(frames),"sizes":[[f.width,f.height] for f in frames],"means":[float(f.to_ndarray(format="rgb24").mean()/255) for f in frames]}
container.close()
if "audio" in streams:
 source=sys.argv[1]
 if source.startswith("base64:"):source=io.BytesIO(base64.b64decode(source[7:]))
 with av.open(source) as c:
  audio=list(c.decode(audio=0));result["audio_samples"]=sum(f.samples for f in audio);result["audio_nonzero"]=any(np.abs(f.to_ndarray()).max()>0.01 for f in audio)
print(json.dumps(result))'''


def decode(container,path):return json.loads(docker('exec',container,'python','-c',DECODE,path))

def check_frames(result,expected):
    if result['frames']!=len(expected) or any(size!=[64,32] for size in result['sizes']):raise RuntimeError('VHS video frame count/dimensions changed')
    if any(abs(v-e/10)>0.025 for v,e in zip(result['means'],expected)):raise RuntimeError('VHS video frame order/values changed')


def combine(images,prefix,**kwargs):
    return {'class_type':'VHS_VideoCombine','inputs':{'images':images,'frame_rate':6,'loop_count':0,'filename_prefix':prefix,'format':'video/h264-mp4','pingpong':False,'save_output':True,'pix_fmt':'yuv420p','crf':19,'save_metadata':False,'trim_to_audio':False,**kwargs}}


def suite(container,base,timeout):
    policy=json.loads((ROOT/'build/adapters/vhs/policy.json').read_text())
    objects=request(base,'/object_info')
    if not set(policy['worker_nodes']).issubset(objects):raise RuntimeError('VHS worker catalog incomplete')
    before=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
    env=json.loads(docker('exec',container,'/opt/workers/videohelpersuite-workernodes/bin/python','-c',ENVIRONMENT,'comfy_env'))
    if env['prefix']!='/opt/workers/videohelpersuite-workernodes' or any(p.startswith('/opt/runtime/venv/') for p in env['sys_path']):raise RuntimeError('VHS worker leaked host environment')
    providers=json.loads(docker('exec',container,'/opt/workers/videohelpersuite-workernodes/bin/python','-c',"import importlib.util,json;print(json.dumps({n:importlib.util.find_spec(n) is not None for n in ['cv2','imageio_ffmpeg']}))"))
    if any(providers.values()):raise RuntimeError('Unused binary providers reappeared in VHS tensor worker')
    media={'class_type':'ComfyctlVHSMedia','inputs':{'count':6}}
    graph={'1':media,'2':{'class_type':'VHS_SelectEveryNthImage','inputs':{'images':['1',0],'select_every_nth':2,'skip_first_images':0}},'3':{'class_type':'VHS_DuplicateImages','inputs':{'images':['2',0],'multiply_by':2}},'4':{'class_type':'ComfyctlVHSInspectImages','inputs':{'data':['3',0],'indices':'0,2,4,0,2,4'}}}
    image=json.loads(execute(base,graph,timeout)['outputs']['4']['text'][0])
    data={}
    for kind,port,node,observer,parameter in [('mask',1,'VHS_SelectMasks','ComfyctlVHSInspectMasks','mask'),('latent',2,'VHS_SelectLatents','ComfyctlVHSInspectLatents','latent')]:
        graph={'1':media,'2':{'class_type':node,'inputs':{parameter:['1',port],'indexes':'0,2,4','err_if_missing':True,'err_if_empty':True}},'3':{'class_type':observer,'inputs':{'data':['2',0],'indices':'0,2,4'}}}
        data[kind]=json.loads(execute(base,graph,timeout)['outputs']['3']['text'][0])
    empty_graph={'1':media,'2':{'class_type':'VHS_SelectImages','inputs':{'image':['1',0],'indexes':'','err_if_missing':True,'err_if_empty':False}},'3':{'class_type':'ComfyctlVHSInspectImages','inputs':{'data':['2',0],'indices':''}},'4':combine(['2',0],'empty-vhs-'+uuid.uuid4().hex[:10])}
    empty=json.loads(execute(base,empty_graph,timeout)['outputs']['3']['text'][0])
    if empty['shape']!=[0,32,64,3]:raise RuntimeError('VHS allowed empty selection was not preserved')
    prefix='vhs-source-'+uuid.uuid4().hex[:10]
    graph={'1':media,'2':combine(['1',0],prefix,audio=['1',3])}
    entry=execute(base,graph,timeout);source=entry['outputs']['2']['gifs'][0]
    source_video=decode(container,source['fullpath']);check_frames(source_video,list(range(6)))
    if not source_video.get('audio_nonzero'):raise RuntimeError('VHS audio mux did not retain sound')
    http={}
    query=urllib.parse.urlencode({k:source[k] for k in ['filename','subfolder','type']})
    for endpoint,kind in [('viewvideo','video'),('viewaudio','audio')]:
        with urllib.request.urlopen(base+'/vhs/'+endpoint+'?'+query,timeout=60) as response:
            blob=response.read();mime=response.headers.get('Content-Type')
        if not blob or not mime.startswith(kind+'/'):raise RuntimeError('VHS streaming route returned no media')
        decoded=decode(container,'base64:'+base64.b64encode(blob).decode())
        if kind=='video':check_frames(decoded,list(range(6)))
        elif not decoded.get('audio_nonzero'):raise RuntimeError('VHS audio streaming is empty')
        http[endpoint]={'mime':mime,'bytes':len(blob),'decoded':decoded}
    # Keep open load/encode generators on host, but pass each tensor sub-batch
    # through the real worker before the host encoder consumes it.
    batch_prefix='vhs-batch-'+uuid.uuid4().hex[:10]
    loader={'class_type':'VHS_LoadVideoPath','inputs':{'video':source['fullpath'],'force_rate':0,'custom_width':0,'custom_height':0,'frame_load_cap':0,'skip_first_frames':0,'select_every_nth':1,'meta_batch':['10',0]}}
    graph={'10':{'class_type':'VHS_BatchManager','inputs':{'frames_per_batch':2}},'11':loader,
           '12':{'class_type':'VHS_SplitImages','inputs':{'images':['11',0],'split_index':1}},
           '13':{'class_type':'VHS_MergeImages','inputs':{'images_A':['12',0],'images_B':['12',2],'merge_strategy':'match A','scale_method':'nearest-exact','crop':'disabled'}},
           '14':combine(['13',0],batch_prefix,meta_batch=['10',0]),
           '15':{'class_type':'ComfyctlVHSBatchAudit','inputs':{'manager':['10',0],'files':['14',0]}}}
    submitted=request(base,'/prompt',{'prompt':graph})
    if submitted.get('node_errors'):raise RuntimeError(str(submitted))
    end=time.monotonic()+timeout;completed=None;entries=[]
    while time.monotonic()<end:
        histories=request(base,'/history')
        entries=[value for value in histories.values() if value['prompt'][2].get('14',{}).get('inputs',{}).get('filename_prefix')==batch_prefix]
        if any(e['status']['status_str']!='success' for e in entries):raise RuntimeError('VHS meta-batch requeue failed: '+json.dumps([e['status'] for e in entries]))
        complete=[e for e in entries if e.get('outputs',{}).get('14',{}).get('gifs')]
        if complete and not any(request(base,'/queue')[key] for key in ['queue_running','queue_pending']):completed=complete[-1];break
        time.sleep(.25)
    if completed is None:raise RuntimeError('VHS meta-batch did not finalize')
    states=[json.loads(e['outputs']['15']['text'][0]) for e in entries if '15' in e.get('outputs',{})]
    if len(entries)<3 or not any(s['suspended_generators']>0 for s in states):raise RuntimeError('VHS test did not retain/requeue a real host generator')
    final=json.loads(completed['outputs']['15']['text'][0])
    if final['inputs'] or final['outputs']:raise RuntimeError('VHS meta-batch generators were not closed')
    output=completed['outputs']['14']['gifs'][0]
    batch_video=decode(container,output['fullpath']);check_frames(batch_video,list(range(6)))
    partial_loader={'class_type':'VHS_LoadVideoPath','inputs':{**loader['inputs'],'meta_batch':['20',0]}}
    partial={'20':{'class_type':'VHS_BatchManager','inputs':{'frames_per_batch':3}},'21':partial_loader,'22':{'class_type':'ComfyctlVHSCaptureInput','inputs':{'manager':['20',0],'images':['21',0],'video_path':source['fullpath']}}}
    partial_state=json.loads(execute(base,partial,timeout)['outputs']['22']['text'][0])
    if partial_state!={'frames':3,'suspended':True}:raise RuntimeError('VHS reset test did not start a partial read')
    reset_graph={'20':{'class_type':'VHS_BatchManager','inputs':{'frames_per_batch':4}},'23':{'class_type':'ComfyctlVHSAssertClosed','inputs':{'manager':['20',0]}}}
    reset=json.loads(execute(base,reset_graph,timeout)['outputs']['23']['text'][0])
    host=json.loads(execute(base,{'1':{'class_type':'ComfyctlVHSHostState','inputs':{}}},timeout)['outputs']['1']['text'][0])
    if not host['queue_is_host'] or not host['latent_hook_preserved'] or host['worker_catalog_imported_on_host'] or host['ffmpeg_path']!='/usr/bin/ffmpeg':raise RuntimeError('VHS host hook/queue/FFmpeg boundary changed')
    rows=json.loads(docker('exec',container,'python','-c',PROCESSES));workers=[p for p in rows if p['cmd'][0]=='/opt/workers/videohelpersuite-workernodes/bin/python']
    if len(workers)!=1 or workers[0]['pid']==host['host_pid'] or any(s['host_pid']!=host['host_pid'] for s in states):raise RuntimeError('VHS state/tensor process boundary changed')
    for node in ['VHS_VideoCombine','VHS_LoadVideoPath','VHS_BatchManager']:
        if host['class_modules'][node]=='comfy_env.isolation.metadata':raise RuntimeError('Stateful VHS node crossed process boundary')
    for node in ['VHS_SplitImages','VHS_SelectLatents']:
        if host['class_modules'][node]!='comfy_env.isolation.metadata':raise RuntimeError('VHS tensor node did not use native proxy')
    assets=[p for p in request(base,'/extensions') if '/ComfyUI-VideoHelperSuite/' in p]
    if not assets:raise RuntimeError('VHS JS assets missing')
    for path in assets:
        with urllib.request.urlopen(base+path,timeout=20) as response:
            if response.status!=200 or not response.read():raise RuntimeError('Missing VHS extension script')
    after=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
    if before!=after:raise RuntimeError('VHS execution changed host packages')
    return {'kind':'vhs-mixed-isolation-cpu-gate','status':'passed','policy':policy,'environment':env,'worker_unused_providers':providers,'image':image,'empty_selection':empty,**data,'source_video':source_video,'http':http,'meta_batch':{'history_count':len(entries),'states':states,'video':batch_video,'final_state':final},'partial_decoder_reset':reset,'host':host,'worker':workers[0],'ui_script_count':len(assets),'host_package_fingerprint':after,'scope':'18 metadata registrations and representative IMAGE/MASK/LATENT values/metadata, H.264+audio, live HTTP transcoding, real host generator requeue through worker tensors and closure. No GPU, real VAE checkpoint, all format or browser interaction certification.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-worker-probe')
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/vhs-cpu-probe.json')
    args=parser.parse_args();args.output.unlink(missing_ok=True)
    fixture=ROOT/'tests/fixtures/vhs-probe-nodes'
    container=docker('run','--detach','--platform','linux/amd64','--name','runpod-vhs-gate-'+uuid.uuid4().hex[:10],'--publish','127.0.0.1::8188','--volume',str(fixture)+':/opt/probe/ComfyUI/custom_nodes/comfyctl_vhs_probe:ro',args.image)
    try:
        port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base='http://127.0.0.1:'+port;end=time.monotonic()+args.timeout
        while True:
            try:request(base,'/system_stats');break
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                state=json.loads(docker('inspect',container))[0]['State']
                if not state['Running'] or time.monotonic()>end:raise RuntimeError('VHS startup failed: '+docker('logs',container))
                time.sleep(1)
        value=suite(container,base,args.timeout);value['image_id']=json.loads(docker('image','inspect',args.image))[0]['Id']
    finally:docker('rm','--force',container)
    value['container_removed']=True
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':value['status'],'meta_batch_histories':value['meta_batch']['history_count'],'isolated_nodes':len(value['policy']['worker_nodes'])}))


if __name__=='__main__':main()
