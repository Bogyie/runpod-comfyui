#!/usr/bin/env python3
"""Check iTools native worker graphs, host routes, data writes and model boundary.

Owns and removes one CPU container. Synthetic VAE dispatch is not real model
inference. Background removal's optional rembg backend is a separate feature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path

from probe_host import ROOT,docker,request,cpu_arguments,service_python,storage_directory
from probe_workers import execute,FINGERPRINT,PROCESSES,ENVIRONMENT


def form(base,path,values):
    body=urllib.parse.urlencode(values).encode()
    req=urllib.request.Request(base+path,data=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)


def rgba_png(rgba):
    def chunk(name,data):return struct.pack('!I',len(data))+name+data+struct.pack('!I',zlib.crc32(name+data)&0xffffffff)
    raw=b''.join(b'\0'+bytes(rgba)*32 for _ in range(32))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',32,32,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def upload_paint(base,user_directory='/opt/probe/ComfyUI/user'):
    boundary='comfyctl-'+uuid.uuid4().hex
    parts=[];images={}
    for field,color in [('foreground',(255,0,0,128)),('background',(0,0,255,255))]:
        data=rgba_png(color);images[field]=data
        header=f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="iToolsPaintedImage_{field}.png"\r\nContent-Type: image/png\r\n\r\n'
        parts.extend([header.encode(),data,b'\r\n'])
    parts.append(f'--{boundary}--\r\n'.encode())
    req=urllib.request.Request(base+'/itools/request_save_paint',data=b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(req,timeout=20) as response:result=json.load(response)
    if result['status']!='success':raise RuntimeError('Paint multipart upload failed')
    for field in images:
        if not result[field].startswith(user_directory+'/comfyctl/itools/paint/'):
            raise RuntimeError('Paint wrote outside user data')
    returned=form(base,'/itools/request_the_paint_file',{'filename_prefix':'iToolsPaintedImage'})
    if any(bytes.fromhex(returned['data'][field])!=data for field,data in images.items()):
        raise RuntimeError('Paint upload/readback bytes differ')
    return {'status':'passed','paths':{f:result[f] for f in images},'sha256':{f:hashlib.sha256(v).hexdigest() for f,v in images.items()}}


def image_result(base,entry,node,key='images'):
    item=entry['outputs'][node][key][0]
    query=urllib.parse.urlencode({k:item[k] for k in ['filename','subfolder','type']})
    with urllib.request.urlopen(base+'/view?'+query,timeout=20) as response:data=response.read()
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise RuntimeError('Missing iTools preview PNG')
    width,height=struct.unpack('!II',data[16:24])
    return {'image':item,'width':width,'height':height,'sha256':hashlib.sha256(data).hexdigest()}



def source_fingerprint(container):
    program = "import hashlib,json,pathlib;root=pathlib.Path('custom_nodes/ComfyUI-iTools');files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts};print(json.dumps({'file_count':len(files),'sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}))"
    return json.loads(docker('exec',container,'python','-c',program))


def suite(container,base,timeout):
    objects=request(base,'/object_info')
    expected=json.loads((ROOT/'locks/upstreams.lock.json').read_text())['sources']['itools']['commit']
    policy=json.loads(docker('exec',container,'python','-c',"from pathlib import Path;print(Path('custom_nodes/ComfyUI-iTools/_comfyctl_policy.json').read_text())"))
    if policy['source_commit']!=expected or not set(policy['base_node_ids']).issubset(objects):raise RuntimeError('iTools catalog incomplete')
    before=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
    source_before=source_fingerprint(container)
    identity=json.loads(docker('exec',container,'python','-c',"from pathlib import Path;print(Path('custom_nodes/ComfyUI-iTools/_comfyctl_adapter_identity.json').read_text())"))
    environment=json.loads(docker('exec',container,'/opt/workers/itools-workernodes/bin/python','-c',ENVIRONMENT,'yaml'))
    if environment['prefix']!='/opt/workers/itools-workernodes' or not environment['extra_realpath'].startswith('/opt/workers/itools-workernodes/') or any(p.startswith('/opt/runtime/venv/') for p in environment['sys_path']):
        raise RuntimeError('iTools dependencies escaped its private venv')

    g={'1':{'class_type':'iToolsTextReplacer','inputs':{'text_in':'alpha cat','match':'cat','replace':'dog'}},'2':{'class_type':'iToolsPromptRecord','inputs':{'text':['1',0],'timeline_data':''}}}
    text=execute(base,g,timeout)
    if text['outputs']['2']['text']!=['alpha dog']:raise RuntimeError('iTools text/V3 UI result changed')
    g={'1':{'class_type':'iToolsCheckerBoard','inputs':{'width':256,'height':256,'rows':4,'cols':4,'pattern':'checkerboard','is_colored':False,'seed':1}},'2':{'class_type':'iToolsPreviewImage','inputs':{'images':['1',0]}}}
    preview=image_result(base,execute(base,g,timeout),'2','itools_preview')
    if [preview['width'],preview['height']]!=[256,256]:raise RuntimeError('Wrong iTools worker image dimensions')
    styles=request(base,'/itools/get_styler_data')['styles']
    if not styles:raise RuntimeError('Missing iTools styles')
    templates=form(base,'/itools/get_style_templates',{'file_name':styles[0]})['templates']
    if not templates:raise RuntimeError('Missing iTools style templates')
    storage=storage_directory(container)
    paint=upload_paint(base,storage+'/user')
    if 'iToolsPaintNode' not in objects:raise RuntimeError('Expected upstream default Paint beta node')
    g={'1':{'class_type':'iToolsPaintNode','inputs':{}},'2':{'class_type':'SaveImage','inputs':{'images':['1',0],'filename_prefix':'itools-paint-gate'}}}
    paint_image=image_result(base,execute(base,g,timeout),'2')
    saved=storage+'/output/'+paint_image['image']['filename']
    pixel=json.loads(docker('exec',container,'python','-c',"import json,sys;from PIL import Image;im=Image.open(sys.argv[1]);print(json.dumps({'size':list(im.size),'pixel':list(im.getpixel((0,0)))}))",saved))
    if pixel!={'size':[32,32],'pixel':[128,0,127]}:raise RuntimeError('Paint composition across host/worker disagrees with uploaded pixels')
    token='comfyctl-'+uuid.uuid4().hex
    g={'1':{'class_type':'iToolsPromptSaver','inputs':{'prompt':token,'file_path':'prompts.txt'}}}
    execute(base,g,timeout)
    prompt_path=storage+'/user/comfyctl/itools/prompts.txt'
    lines=json.loads(docker('exec',container,'python','-c',"from pathlib import Path;import json,sys;print(json.dumps([x for x in Path(sys.argv[1]).read_text().splitlines() if x.strip()]))",prompt_path))
    if lines[-1]!=token:raise RuntimeError('Default prompt saver did not write user data')
    g={'1':{'class_type':'iToolsPromptLoader','inputs':{'file_path':'prompts.txt','seed':len(lines)-1}},'2':{'class_type':'iToolsPromptRecord','inputs':{'text':['1',0],'timeline_data':''}}}
    if execute(base,g,timeout)['outputs']['2']['text']!=[token]:raise RuntimeError('Saved prompt did not round trip')
    g={'1':{'class_type':'ComfyctlIToolsSyntheticVAE','inputs':{}},'2':{'class_type':'iToolsVaePreview','inputs':{'samples':['1',0],'vae':['1',1],'filename_prefix':'itools-vae-gate'}}}
    vae=image_result(base,execute(base,g,timeout),'2')
    if [vae['width'],vae['height']]!=[8,8]:raise RuntimeError('Synthetic host VAE dispatch failed')
    state=execute(base,{'1':{'class_type':'ComfyctlIToolsHostState','inputs':{}}},timeout)
    host=json.loads(state['outputs']['1']['text'][0])
    if host['worker_catalog_imported_on_host'] or {n.rsplit('.',1)[-1] for n in host['host_compute_imports']}!={'ksampler','vae_preview'}:raise RuntimeError('iTools compute imports leaked onto host')
    rows=json.loads(service_python(container,PROCESSES))
    workers=[p for p in rows if '/opt/workers/itools-workernodes/bin/python'==p['cmd'][0]]
    if len(workers)!=1 or workers[0]['pid']==host['host_pid'] or workers[0]['cpu_mode']!='1':raise RuntimeError('iTools did not use a separate persistent worker')
    extensions=request(base,'/extensions');assets=[p for p in extensions if '/ComfyUI-iTools/' in p]
    if not assets:raise RuntimeError('No iTools UI assets registered')
    for path in assets:
        with urllib.request.urlopen(base+path,timeout=20) as response:
            if response.status!=200 or not response.read():raise RuntimeError('Missing iTools UI script')
    after=json.loads(docker('exec',container,'python','-c',FINGERPRINT))
    if before!=after:raise RuntimeError('iTools execution changed host packages')
    if source_fingerprint(container)!=source_before:raise RuntimeError('iTools execution changed node source/assets')
    return {'kind':'itools-mixed-isolation-cpu-gate','status':'passed','policy':policy,'adapter_identity':identity,'source_fingerprint':source_before,'source_unchanged':True,'environment':environment,'text_v1_to_v3_ui':'passed','preview':preview,'paint':{**paint,'output':paint_image,'pixel':pixel},'style_file':styles[0],'style_template_count':len(templates),'prompt_default_roundtrip':'passed','synthetic_host_vae':vae,'host':host,'worker':workers[0],'ui_script_count':len(assets),'host_package_fingerprint':after,'scope':'CPU text/image/V3 UI, style/paint HTTP, data paths, synthetic host VAE dispatch only. No real KSampler/VAE checkpoint, GPU or browser interaction certification.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-worker-probe')
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/itools-cpu-probe.json')
    args=parser.parse_args();args.output.unlink(missing_ok=True)
    fixture=ROOT/'tests/fixtures/itools-probe-nodes'
    name='runpod-itools-gate-'+uuid.uuid4().hex[:10]
    container=docker('run','--detach','--platform','linux/amd64','--name',name,'--publish','127.0.0.1::8188','--volume',str(fixture)+':/opt/probe/ComfyUI/custom_nodes/comfyctl_itools_probe:ro',args.image,*cpu_arguments(args.image))
    try:
        port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base='http://127.0.0.1:'+port;end=time.monotonic()+args.timeout
        while True:
            try:request(base,'/system_stats');break
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                if time.monotonic()>end:raise RuntimeError('iTools candidate startup timed out: '+docker('logs',container))
                time.sleep(1)
        value=suite(container,base,args.timeout)
        value['image_id']=json.loads(docker('image','inspect',args.image))[0]['Id']
    finally:
        docker('rm','--force',container)
    value['container_removed']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':value['status'],'ui_script_count':value['ui_script_count']}))


if __name__=='__main__':main()
