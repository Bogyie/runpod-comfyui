#!/usr/bin/env python3
"""Boot real compatible image variants against one persistent selection volume."""
import argparse
import hashlib
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, cli, inside, state
from probe_workers import FINGERPRINT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/image-compatibility-cpu.json')
    args=parser.parse_args()
    args.output.unlink(missing_ok=True)
    image=json.loads(docker('image','inspect',args.image))[0]['Id']
    token=uuid.uuid4().hex[:10]
    volume='comfy-image-history-'+token
    containers=[]
    variants=[]
    result={'kind':'image-compatibility-cpu-gate','image_id':image,
            'scope':'Real CLI-only image update, persistent selections and rollback; synthetic foreign contract refusal. No application rebase, GPU or network-volume certification.'}
    docker('volume','create',volume)

    def launch(tag,suffix):
        container=docker('run','--detach','--platform','linux/amd64','--name','comfy-image-'+token+suffix,
            '--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m',
            '--mount','type=volume,source='+volume+',target=/workspace',
            '--publish','127.0.0.1::8188',tag,'--cpu','--use-pytorch-cross-attention',
            '--listen','0.0.0.0','--port','8188')
        containers.append(container)
        return container

    def ready(container,enabled):
        record=await_ready(container,300)
        port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        assert ('iToolsCheckerBoard' in request('http://127.0.0.1:'+port,'/object_info'))==enabled
        return record

    def stop(container):
        docker('stop','--time','25',container)
        assert json.loads(docker('inspect',container))[0]['State']['ExitCode']==0

    try:
        base_tag='comfy-image-base:'+token
        docker('tag',image,base_tag)
        variants.append(base_tag)
        with tempfile.TemporaryDirectory(prefix='comfy-image-fixture-') as temporary:
            context=Path(temporary)
            source=docker('create',image)
            containers.append(source)
            for source_path,target in [('/opt/runtime/control/identity.json','identity.json'),
                    ('/opt/runtime/control/baseline.json','baseline.json'),
                    ('/opt/comfyctl/src/comfyctl/cli.py','cli.py')]:
                docker('cp',source+':'+source_path,str(context/target))
            baseline=json.loads((context/'baseline.json').read_text())
            identity=json.loads((context/'identity.json').read_text())
            original=(context/'cli.py').read_text()
            anchor='argparse.ArgumentParser(prog="comfyctl")'
            assert original.count(anchor)==1
            updated=original.replace(anchor,'argparse.ArgumentParser(prog="comfyctl", description="Image compatibility fixture")')
            (context/'cli.py').write_text(updated)
            identity['inputs']['tools/comfyctl/cli.py']=hashlib.sha256(updated.encode()).hexdigest()
            identity['runtime_id']=hashlib.sha256(json.dumps(identity['inputs'],sort_keys=True).encode()).hexdigest()
            baseline['runtime_id']=identity['runtime_id']
            for name,value in [('identity',identity),('baseline',baseline)]:
                (context/(name+'.json')).write_text(json.dumps(value))
            (context/'Dockerfile').write_text('FROM '+base_tag+'\nCOPY identity.json baseline.json /opt/runtime/control/\nCOPY cli.py /opt/comfyctl/src/comfyctl/cli.py\n')
            compatible='comfy-image-compatible:'+token
            variants.append(compatible)
            subprocess.run(['docker','build','--platform','linux/amd64','-t',compatible,str(context)],check=True)
            # A deliberately synthetic fixture, not evidence of a ComfyUI upgrade.
            baseline['compatibility_id']=hashlib.sha256(b'synthetic-foreign-contract').hexdigest()
            baseline['application_id']=hashlib.sha256(b'synthetic-foreign-application').hexdigest()
            (context/'baseline.json').write_text(json.dumps(baseline))
            foreign='comfy-image-foreign:'+token
            variants.append(foreign)
            subprocess.run(['docker','build','--platform','linux/amd64','-t',foreign,str(context)],check=True)

        a=launch(image,'-a')
        ready(a,True)
        fingerprint=inside(a,FINGERPRINT)
        inside(a,"import json;from pathlib import Path;Path('/workspace/storage/user/image-marker').write_text('preserved');print(json.dumps(True))")
        old=cli(a,'node','disable','itools','--defer')['selection']['desired']
        stop(a)
        b=launch(compatible,'-b')
        assert ready(b,False)['generation_id']==old
        assert 'Image compatibility fixture' in docker('exec',b,'comfyctl','--help')
        assert inside(b,FINGERPRINT)==fingerprint
        new=cli(b,'node','enable','itools','--defer')['selection']['desired']
        stop(b)
        a=launch(image,'-return')
        assert ready(a,True)['generation_id']==new
        rolled=cli(a,'env','rollback','--defer')['selection']['desired']
        assert rolled==old
        stop(a)
        c=launch(foreign,'-foreign')
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if state(c)['phase']=='recovery-required':break
            time.sleep(1)
        else:raise AssertionError('Foreign image did not enter recovery mode')
        preserved=inside(c,"import json;from pathlib import Path;print(Path('/workspace/runtime/control/selection.json').read_text())")
        assert preserved['desired']==old
        cli(c,'env','reset','--defer')
        gc=cli(c,'env','gc','--min-age-hours','0')
        assert old in gc['retained']
        stop(c)
        a=launch(image,'-restored')
        assert ready(a,False)['generation_id']==old
        assert inside(a,FINGERPRINT)==fingerprint
        assert inside(a,"import json;from pathlib import Path;print(json.dumps(Path('/workspace/storage/user/image-marker').read_text()))")=='preserved'
        stop(a)
        result.update(compatible_runtime_id=identity['runtime_id'],preserved_generation=old,
                      new_generation=new,rollback_generation=rolled,foreign_recovery=True,
                      foreign_gc_retained=gc['retained'],data_and_packages_unchanged=True)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print(json.dumps(result,indent=2))
    finally:
        for container in reversed(containers):
            subprocess.run(['docker','rm','--force',container],capture_output=True)
        subprocess.run(['docker','volume','rm',volume],capture_output=True)
        for tag in reversed(variants):subprocess.run(['docker','image','rm',tag],capture_output=True)


if __name__=='__main__':main()
