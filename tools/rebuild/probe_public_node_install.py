#!/usr/bin/env python3
"""Install pinned public Multiband with automatic resolution and real tensor/UI IO."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import uuid

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, cli, inside
from probe_workers import execute, FINGERPRINT, PROCESSES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output', type=Path, default=ROOT/'tests/evidence/public-node-install-cpu.json')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    pin = json.loads((ROOT/'locks/upstreams.lock.json').read_text())['sources']['multiband']
    image_id = json.loads(docker('image','inspect',args.image))[0]['Id']
    token=uuid.uuid4().hex[:10]
    volume='comfy-public-install-'+token
    docker('volume','create',volume)
    container=None
    result={'kind':'public-node-auto-resolution-cpu-gate','image_id':image_id,
            'repository':pin['repository'],'commit':pin['commit'],
            'scope':'Pinned public Multiband source, automatic wheel resolution, CPU tensor/dict/preview/static assets and reset; no full UI/GPU/network-volume certification'}
    graph={'1':{'class_type':'EmptyImage','inputs':{'width':64,'height':32,'batch_size':1,'color':0x112233}},
           '2':{'class_type':'MultibandFromImage','inputs':{'image':['1',0],'channel_names':'R,G,B'}},
           '3':{'class_type':'MultibandToImage','inputs':{'multiband':['2',0],'channels':'2,1,0'}},
           '4':{'class_type':'SaveImage','inputs':{'images':['3',0],'filename_prefix':'public-multiband'}},
           '5':{'class_type':'MultibandPreview','inputs':{'multiband':['2',0],'channel_index':1}}}
    with tempfile.TemporaryDirectory(prefix='public-node-fixture-') as temporary:
        fixture=Path(temporary)
        (fixture/'smoke.json').write_text(json.dumps(graph))
        try:
            container=docker('run','--detach','--platform','linux/amd64','--name',volume,'--read-only',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m',
                '--mount','type=volume,source='+volume+',target=/workspace',
                '--mount','type=bind,source='+str(fixture)+',target=/opt/public-node-fixture,readonly',
                '--publish','127.0.0.1::8188',args.image,'--cpu','--use-pytorch-cross-attention','--listen','0.0.0.0','--port','8188')
            await_ready(container,300)
            port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
            base='http://127.0.0.1:'+port
            fingerprint=inside(container,FINGERPRINT)
            added=cli(container,'node','add',pin['repository'],'--name','multiband','--commit',pin['commit'],
                '--archive-sha256',pin['archive_sha256'],'--skip-hooks','--required-node','MultibandFromImage',
                '--required-node','MultibandToImage','--required-node','MultibandPreview',
                '--smoke-workflow','/opt/public-node-fixture/smoke.json','--restart')
            assert added['live_transition']=='committed'
            generation=added['selection']['desired']
            print('Public source resolved, installed and applied',flush=True)
            entry=execute(base,graph,180)
            output=entry['outputs']['4']['images'][0]
            image_path='/workspace/storage/output/'+output['subfolder']+'/'+output['filename']
            image=inside(container,'import json;from PIL import Image;p=Image.open('+repr(image_path)+');print(json.dumps({"size":list(p.size),"pixel":list(p.getpixel((0,0)))}))')
            assert image['size']==[64,32] and all(abs(a-b)<=1 for a,b in zip(image['pixel'],[51,34,17]))
            assert entry['outputs']['5']['images']
            extensions=[p for p in request(base,'/extensions') if 'ComfyUI-multiband/' in p]
            assert extensions
            for path in extensions:
                with urllib.request.urlopen(base+path,timeout=10) as response:
                    assert response.status==200 and response.read(1)
            workers=inside(container,PROCESSES)
            worker=next(p for p in workers if p['cmd'][0].startswith('/workspace/runtime/generations/'))
            prefix=worker['cmd'][0].removesuffix('/bin/python')
            package=json.loads(docker('exec','--user','1000:1000',container,prefix+'/bin/python','-I','-c',
                'import json,tifffile;print(json.dumps({"file":tifffile.__file__,"version":tifffile.__version__}))'))
            assert package['file'].startswith(prefix+'/')
            nnp=inside(container,"import json;from pathlib import Path;print(json.dumps(next(p for p in Path('/proc/"+str(worker['pid'])+"/status').read_text().splitlines() if p.startswith('NoNewPrivs:')).split()[-1]))")
            assert nnp=='1'
            metadata=inside(container,"import json;from pathlib import Path;print(Path('/workspace/runtime/generations/"+generation+"/resolution/receipt.json').read_text())")
            assert metadata['resolver_uid']==1001 and not metadata['installed'] and not metadata['selected']
            assert inside(container,FINGERPRINT)==fingerprint
            reset=cli(container,'env','reset','--restart')
            assert reset['live_transition']=='committed' and 'MultibandFromImage' not in request(base,'/object_info')
            result.update(status='passed',selection=added['selection'],resolved=metadata,worker=worker,
                cpu_image=image,preview_images=len(entry['outputs']['5']['images']),static_assets=extensions,
                private_tifffile=package,worker_no_new_privs=True,image_package_fingerprint_unchanged=True,image_reset='passed')
        except Exception:
            if container:
                logs=subprocess.run(['docker','logs',container],capture_output=True,text=True)
                details=subprocess.run(['docker','exec',container,'sh','-c','cat /workspace/runtime/generations/*/resolution/resolve.log /workspace/runtime/generations/*/validation.log /workspace/runtime/generations/*/environment-*/install.log'],capture_output=True,text=True)
                (ROOT/'.work/public-node-install-failure.log').write_text((logs.stdout+logs.stderr)[-18000:]+details.stdout[-26000:]+details.stderr[-2000:])
            raise
        finally:
            if container:docker('rm','--force',container)
            docker('volume','rm',volume)
    result['container_and_volume_removed']=True
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','image_id':image_id}))


if __name__=='__main__':main()
