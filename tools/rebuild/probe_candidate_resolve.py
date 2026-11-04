#!/usr/bin/env python3
"""Verify actual resolver constraints and isolation from a malformed user config."""
import argparse
import json
import subprocess
import uuid
from pathlib import Path

from probe_host import ROOT, docker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/candidate-resolve-linux.json')
    args=parser.parse_args()
    args.output.unlink(missing_ok=True)
    volume='comfy-resolver-'+uuid.uuid4().hex[:10]
    docker('volume','create',volume)
    code=r'''import json,os,sys,uuid
from pathlib import Path
sys.path.insert(0,'/opt/comfyctl/src')
from comfyctl.candidate_resolve import resolve_environment
from comfyctl.candidate_env import CandidateEnvironmentError,frozen_pins
parent=Path('/workspace/runtime/generations');parent.mkdir(parents=True)
noise=Path('/workspace/user-config');noise.mkdir();(noise/'uv.toml').write_text('invalid = [')
os.chdir(noise)
good=parent/uuid.uuid4().hex;good.mkdir()
data=resolve_environment(good,[])
pins=frozen_pins(data)
assert pins['torch']=='2.10.0+cu128' and pins['comfy-env']=='0.3.89'
assert 'comfyui-frontend-package' not in pins
assert not (good/'resolution/scratch').exists()
bad=parent/uuid.uuid4().hex;bad.mkdir()
try:resolve_environment(bad,['torch==2.9.0'])
except CandidateEnvironmentError:pass
else:raise RuntimeError('Conflicting GPU requirement accepted')
log=(bad/'resolution/resolve.log').read_text()
assert 'no solution found' in log.lower() and 'torch' in log and '2.9.0' in log
assert not (bad/'resolution/scratch').exists()
assert not Path('/workspace/runtime/control/selection.json').exists()
assert not list(parent.glob('*/environment-*'))
print(json.dumps({'status':'passed','kind':'candidate-resolution-linux-cpu','resolved_packages':len(pins),
 'malformed_user_uv_config':'ignored','gpu_conflict':'rejected-before-install','selected':False,
 'environment_installed':False,'scratch_removed':True}))
'''
    try:
        process=subprocess.run(['docker','run','--rm','--platform','linux/amd64','--read-only',
            '--mount','type=volume,source='+volume+',target=/workspace','--tmpfs','/tmp:rw,nosuid,nodev,size=64m',
            '--entrypoint','/opt/comfyctl/venv/bin/python',args.image,'-I','-c',code],capture_output=True,text=True,check=True,timeout=180)
        result=json.loads(process.stdout)
        result['image_id']=json.loads(docker('image','inspect',args.image))[0]['Id']
    finally:
        docker('volume','rm',volume)
    result['container_and_volume_removed']=True
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
