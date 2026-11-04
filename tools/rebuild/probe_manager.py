#!/usr/bin/env python3
"""Verify pinned Manager catalog/assets and every legacy mutation boundary."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
import uuid

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, inside, cli
from probe_workers import FINGERPRINT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output',type=Path,default=ROOT/'tests/evidence/manager-cpu-probe.json')
    args=parser.parse_args()
    args.output.unlink(missing_ok=True)
    image_id=json.loads(docker('image','inspect',args.image))[0]['Id']
    token=uuid.uuid4().hex[:10];volume='comfy-manager-'+token
    docker('volume','create',volume);container=None
    result={'kind':'managed-manager-cpu-gate','image_id':image_id,
            'scope':'Pinned original Manager frontend/catalog with read-only adapter and legacy entrypoint guards; CLI installation is a separate gate. No GPU/network-volume certification'}
    try:
        seed=r'''import hashlib,json
from pathlib import Path
root=Path('/workspace/storage/user/__manager/startup-scripts');root.mkdir(parents=True)
payload=repr(['/workspace','python','-c',"from pathlib import Path;Path('/workspace/storage/user/manager-should-not-run').touch()"])
(root/'install-scripts.txt').write_text(payload+'\n')
(root/'restore-snapshot.json').write_text('{"git_custom_nodes":{},"pypi_packages":{"torch":"0"}}')
print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}))
'''
        queued=json.loads(docker('run','--rm','--platform','linux/amd64','--mount','type=volume,source='+volume+',target=/workspace',
            '--entrypoint','/usr/local/bin/python',args.image,'-c',seed))
        container=docker('run','--detach','--platform','linux/amd64','--name',volume,'--read-only','--network','bridge',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m',
            '--mount','type=volume,source='+volume+',target=/workspace','--publish','127.0.0.1::8188',
            args.image,'--cpu','--use-pytorch-cross-attention','--listen','0.0.0.0','--port','8188')
        await_ready(container,300)
        port=json.loads(docker('inspect',container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base='http://127.0.0.1:'+port
        fingerprint=inside(container,FINGERPRINT)
        status=request(base,'/comfyctl/manager/status')
        assert status['manager_commit']=='4c50a2bc8b9e684d8a85930567957470b952bebe' and status['direct_mutations'] is False
        catalog=request(base,'/customnode/getlist?mode=remote')['node_packs']
        assert len(catalog)>=6025
        installed=[item for item in catalog.values() if item['managed']]
        assert len(installed)==6 and all(item['state']=='enabled' for item in installed)
        assert len([p for p in installed if p['title']=='ComfyUI-Manager'])==1
        mappings=request(base,'/customnode/getmappings?mode=remote');assert len(mappings)>100
        extensions=[p for p in request(base,'/extensions') if '/ComfyUI-Manager/' in p]
        assert any(p.endswith('/comfyui-manager.js') for p in extensions)
        for path in extensions:
            with urllib.request.urlopen(base+path,timeout=10) as response:
                assert response.status==200 and response.read(1)
        audit=json.loads((ROOT/'docs/evidence/manager-boundary-audit.json').read_text())
        denied=[]
        for route in audit['http_routes']:
            if route['method']!='post':continue
            path=route['path']
            for prefix in ['', '/api']:
                try:
                    request(base,prefix+path,{})
                    raise AssertionError('Legacy mutation accepted: '+path)
                except urllib.error.HTTPError as error:
                    assert error.code==403 and b'comfyctl' in error.read()
            denied.append(path)
        for path in ['/manager/share_option?value=all','/snapshot/get_current','/manager/unknown-mutation']:
            try:request(base,path)
            except urllib.error.HTTPError as error:assert error.code==403
            else:raise AssertionError('Unreviewed Manager read/mutation accepted')
        legacy=[]
        for name in ['cm-cli.py','glob/manager_util.py','glob/manager_core.py','glob/manager_server.py','glob/share_3rdparty.py','git_helper.py']:
            process=subprocess.run(['docker','exec','--user','1000:1000',container,'python','-I','/opt/probe/ComfyUI/custom_nodes/ComfyUI-Manager/'+name],capture_output=True,text=True)
            assert process.returncode!=0 and 'comfyctl' in process.stdout+process.stderr
            legacy.append(name)
        preserved=inside(container,"import json,hashlib;from pathlib import Path;r=Path('/workspace/storage/user/__manager/startup-scripts');print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in r.iterdir()}))")
        assert preserved==queued
        blocked=inside(container,"from pathlib import Path;print(Path('/workspace/storage/user/comfyctl/manager/blocked-startup.json').read_text())")
        assert len(blocked['pending'])==2
        assert inside(container,"import json;from pathlib import Path;print(json.dumps(not Path('/workspace/storage/user/manager-should-not-run').exists()))")
        assert inside(container,FINGERPRINT)==fingerprint
        cli(container,'node','disable','manager','--restart')
        await_ready(container,300)
        try:request(base,'/comfyctl/manager/status')
        except urllib.error.HTTPError as error:assert error.code==404
        else:raise AssertionError('Disabled Manager still exposes its routes')
        assert 'EmptyImage' in request(base,'/object_info')
        cli(container,'node','enable','manager','--restart')
        await_ready(container,300)
        assert request(base,'/comfyctl/manager/status')['direct_mutations'] is False
        # A boot with the same volume and no network must retain the catalog and
        # preserve pending records without executing an installer or fetcher.
        docker('stop','--time','25',container)
        docker('rm',container);container=None
        container=docker('run','--detach','--platform','linux/amd64','--name',volume+'-offline','--read-only','--network','none',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--shm-size','512m','--mount','type=volume,source='+volume+',target=/workspace',
            args.image,'--cpu','--use-pytorch-cross-attention','--listen','0.0.0.0','--port','8188')
        await_ready(container,300)
        offline=inside(container,"import json,urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8188/comfyctl/manager/status').read().decode())")
        assert offline['catalog_entries']==status['catalog_entries']
        result.update(status='passed',manager=status,ui_catalog_rows=len(catalog),installed=installed,
            static_assets_checked=len(extensions),denied_mutations=denied,api_aliases_denied=True,
            legacy_entrypoints_denied=legacy,pending_files_preserved=queued,
            pending_actions='never-executed',offline_boot='passed',image_package_fingerprint_unchanged=True)
        result['manager_disable_enable_restart']='passed'
    except Exception:
        if container:
            logs=subprocess.run(['docker','logs',container],capture_output=True,text=True)
            (ROOT/'.work/manager-gate-failure.log').write_text((logs.stdout+logs.stderr)[-24000:])
        raise
    finally:
        if container:docker('rm','--force',container)
        docker('volume','rm',volume)
    result['container_and_volume_removed']=True
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','image_id':image_id}))


if __name__=='__main__':main()
