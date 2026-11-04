#!/usr/bin/env python3
"""Build a real private prefix and inject install failures without selecting it."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid

from probe_host import ROOT, docker
from probe_workers import FINGERPRINT


def execute(container, code, user='0:0'):
    return json.loads(docker('exec', '--user', user, container, '/opt/comfyctl/venv/bin/python', '-I', '-c', code))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/evidence/candidate-environment-cpu.json')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    image_id = json.loads(docker('image', 'inspect', args.image))[0]['Id']
    token = uuid.uuid4().hex
    volume = 'comfy-env-build-' + token
    docker('volume', 'create', volume)
    container = None
    result = {'kind': 'candidate-environment-installer-cpu-gate', 'image_id': image_id,
              'scope': 'Internal final-prefix builder only; no node add/update, generation selection, Manager, GPU kernels or network-volume certification'}
    try:
        container = docker('run', '--detach', '--platform', 'linux/amd64', '--name', volume, '--read-only',
                           '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m', '--mount', 'type=volume,source=' + volume + ',target=/workspace',
                           '--entrypoint', '/usr/local/bin/python', args.image, '-c', 'import time;time.sleep(1800)')
        fingerprint = json.loads(docker('exec', container, '/opt/runtime/venv/bin/python', '-I', '-c', FINGERPRINT))
        setup = """import json,os
from pathlib import Path
root=Path('/workspace/runtime/generations')/TOKEN
root.mkdir(parents=True)
control=Path('/workspace/runtime/control');control.mkdir()
(control/'selection.json').write_text('{"desired":"unchanged-by-builder"}')
user=Path('/workspace/storage/user');user.mkdir(parents=True);os.chown(user,1000,1000);user.chmod(0o700)
sentinel=user/'sentinel';sentinel.write_text('preserve');os.chown(sentinel,1000,1000);sentinel.chmod(0o600)
print(json.dumps(str(root)))
"""
        generation = execute(container, 'TOKEN=' + repr(token) + '\n' + setup)
        build = """import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'/opt/comfyctl/src')
from comfyctl.candidate_env import prepare_environment
lock=Path('/opt/locks/host.txt').read_bytes()
print(json.dumps(prepare_environment(Path(GENERATION),'host-copy',lock,hashlib.sha256(lock).hexdigest())))
"""
        receipt = execute(container, 'GENERATION=' + repr(generation) + '\n' + build)
        prefix = receipt['prefix']
        assert receipt['installer_uid'] == 1001 and receipt['selected'] is False
        probe = """import importlib.util,json,os,sys
from pathlib import Path
import torch
site=Path(sys.prefix)/'lib/python3.11/site-packages'
numpy=Path(importlib.util.find_spec('numpy').origin)
assert str(numpy).startswith(str(site)) and not numpy.is_symlink()
assert (site/'torch').is_symlink()
assert not any(p.startswith('/opt/runtime/venv/lib/') for p in sys.path)
denied=False
try:numpy.write_text('forbidden')
except PermissionError:denied=True
assert denied
print(json.dumps({'prefix':sys.prefix,'numpy_path':str(numpy),'torch_path':str(Path(torch.__file__).resolve()),'uid':os.getuid(),'candidate_write_denied':denied}))
"""
        runtime = json.loads(docker('exec', '--user', '1000:1000', container, prefix + '/bin/python', '-I', '-c', probe))
        assert runtime['prefix'] == prefix
        failed = r"""import hashlib,json,re,sys
from pathlib import Path
sys.path.insert(0,'/opt/comfyctl/src')
from comfyctl.candidate_env import prepare_environment,CandidateEnvironmentError
root=Path(GENERATION)
original=Path('/opt/locks/host.txt').read_text()
bad=original.replace('torch==2.10.0+cu128','torch==2.9.0')
assert bad!=original
try:prepare_environment(root,'gpu-mismatch',bad.encode(),hashlib.sha256(bad.encode()).hexdigest())
except CandidateEnvironmentError:pass
else:raise RuntimeError('GPU mismatch accepted')
assert not (root/'environment-gpu-mismatch').exists()
lines=[];inside=False
for line in original.splitlines():
    if line and not line[0].isspace() and not line.startswith('#'):inside=line.startswith('aiofiles==')
    if inside and '--hash=sha256:' in line:line=re.sub(r'(?<=sha256:)[0-9a-f]{64}','0'*64,line)
    lines.append(line)
bad=('\n'.join(lines)+'\n').encode()
assert bad!=original.encode()
try:prepare_environment(root,'bad-wheel-hash',bad,hashlib.sha256(bad).hexdigest())
except CandidateEnvironmentError:pass
else:raise RuntimeError('Bad artifact hash accepted')
failed=root/'environment-bad-wheel-hash'
log=(failed/'install.log').read_text()
assert 'hash' in log.lower() and (failed/'failed.json').exists()
try:prepare_environment(root,'bad-wheel-hash',bad,hashlib.sha256(bad).hexdigest())
except FileExistsError:pass
else:raise RuntimeError('Failed final prefix was reused')
assert json.loads(Path('/workspace/runtime/control/selection.json').read_text())=={'desired':'unchanged-by-builder'}
assert Path('/workspace/storage/user/sentinel').read_text()=='preserve'
print(json.dumps({'gpu_mismatch':'rejected-before-prefix-creation','bad_artifact_hash':'failed-and-sealed','failed_prefix_reuse':'rejected','selection':'unchanged','user_data':'preserved'}))
"""
        failures = execute(container, 'GENERATION=' + repr(generation) + '\n' + failed)
        data_boundary = execute(container, "import json;from pathlib import Path\np=Path('/workspace/storage/user/sentinel')\ntry:p.write_text('forbidden')\nexcept PermissionError:print(json.dumps(True))\nelse:raise RuntimeError('Installer wrote private user data')", user='1001:1001')
        assert data_boundary is True
        after = json.loads(docker('exec', container, '/opt/runtime/venv/bin/python', '-I', '-c', FINGERPRINT))
        assert fingerprint == after
        result.update(status='passed', receipt=receipt, runtime=runtime, failures=failures,
                      installer_user_data_write_denied=True, image_package_fingerprint_unchanged=True,
                      resolver_cache_removed=execute(container, 'import json;from pathlib import Path;print(json.dumps(not Path(' + repr(generation + '/environment-host-copy/installer') + ').exists()))'))
    except Exception:
        if container:
            logs = subprocess.run(['docker', 'exec', container, 'sh', '-c', "cat /workspace/runtime/generations/*/environment-*/install.log"], capture_output=True, text=True)
            (ROOT / '.work/candidate-env-failure.log').write_text(logs.stdout[-20000:] + logs.stderr[-2000:])
        raise
    finally:
        if container:
            docker('rm', '--force', container)
        docker('volume', 'rm', volume)
    result['container_and_volume_removed'] = True
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'image_id': image_id}))


if __name__ == '__main__':
    main()
