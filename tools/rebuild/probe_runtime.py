#!/usr/bin/env python3
"""Verify nonroot runtime, shared data paths, restart persistence and failure state."""
import argparse
import json
import struct
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zlib
from pathlib import Path

from probe_host import ROOT, docker, request, verify_frontend
from comfyctl.environments import locked_versions
from probe_workers import execute, points, PROCESSES, FINGERPRINT


def inside(container, code):
    return json.loads(docker('exec', '--user', '1000:1000', container, 'python', '-c', code))


def state(container):
    return inside(container, "import json;from pathlib import Path;p=Path('/workspace/state/runtime-status.json');print(p.read_text() if p.exists() else json.dumps({'phase':'bootstrap'}))")


def await_ready(container, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        details = json.loads(docker('inspect', container))[0]
        if not details['State']['Running']:
            raise RuntimeError('Runtime exited before readiness:\n' + docker('logs', container))
        try:
            result = state(container)
            if result['phase'] == 'ready':
                return result
        except subprocess.CalledProcessError:
            pass
        time.sleep(1)
    raise RuntimeError('Runtime readiness timed out:\n' + docker('logs', container))


def png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\x40\x80\xc0')) + chunk(b'IEND', b'')



def cli(container, *arguments, expected=0):
    process = subprocess.run(['docker', 'exec', '--env', 'PYTHONPATH=/opt/runtime/venv/lib/python3.11/site-packages',
                              container, 'comfyctl', *arguments], text=True, capture_output=True, timeout=600)
    if process.returncode != expected:
        raise RuntimeError('CLI result disagrees: ' + (process.stderr + process.stdout)[-8000:])
    return json.loads(process.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--live-downloads', action='store_true', help='Also download pinned public HF/Civitai fixtures')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/evidence/runtime-cpu-probe.json')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    image_id = json.loads(docker('image', 'inspect', args.image))[0]['Id']
    token = uuid.uuid4().hex[:10]
    volume = 'comfy-runtime-volume-' + token
    containers = []
    docker('volume', 'create', volume)
    result = {'kind': 'nonroot-runtime-cpu-gate', 'image_id': image_id,
              'scope': 'Disposable local Linux amd64 runtime; no Manager integration, GPU, network volume or arbitrary node installation certification'}
    fixture = ROOT / 'tests/fixtures/runtime-probe-nodes'
    temporary = tempfile.TemporaryDirectory(prefix='comfy-runtime-gate-')
    corrupt_file = Path(temporary.name) / 'torch_version.py'

    def launch(suffix, offline=False, invalid=False, corrupt=False):
        name = 'comfy-runtime-' + token + suffix
        command = ['run', '--detach', '--platform', 'linux/amd64', '--name', name, '--read-only',
                   '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m', '--shm-size', '512m',
                   '--mount', 'type=volume,source=' + volume + ',target=/workspace',
                   '--mount', 'type=bind,source=' + str(fixture) + ',target=/opt/probe/ComfyUI/custom_nodes/RuntimeGate,readonly']
        if corrupt:
            command += ['--mount', 'type=bind,source=' + str(corrupt_file) + ',target=/opt/runtime/venv/lib/python3.11/site-packages/torch/version.py,readonly']
        if args.live_downloads:
            command += ['--mount', 'type=bind,source=' + str(ROOT / 'tests/fixtures/models-smoke.yaml') + ',target=/opt/runtime/provider-fixtures.yaml,readonly']
        command += ['--network', 'none'] if offline else ['--publish', '127.0.0.1::8188']
        command += [args.image, '--invalid-runtime-test-flag'] if invalid else [args.image, '--cpu', '--use-pytorch-cross-attention', '--listen', '0.0.0.0', '--port', '8188']
        container = docker(*command)
        containers.append(container)
        return container

    try:
        first = launch('-first')
        # Seed only test data, as the service account, after bootstrap prepared directories.
        deadline = time.monotonic() + args.timeout
        while True:
            try:
                inside(first, "from pathlib import Path;import json;p=Path('/workspace/storage/models/checkpoints');p.mkdir(parents=True,exist_ok=True);(p/'runtime-marker.safetensors').write_text('model-path-marker');Path('/workspace/storage/user/persistence.txt').write_text('keep-me');print(json.dumps(True))")
                break
            except subprocess.CalledProcessError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        result['first_ready'] = await_ready(first, args.timeout)
        port = json.loads(docker('inspect', first))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base = 'http://127.0.0.1:' + port
        result['frontend'] = verify_frontend(base)
        child_pid = result['first_ready']['child_pid']
        inside(first, f"import os,signal,json;os.kill({child_pid},signal.SIGSTOP);print(json.dumps(True))")
        try:
            deadline = time.monotonic() + 15
            while state(first)['phase'] != 'recovery-required':
                if time.monotonic() > deadline:
                    raise RuntimeError('Hung API stayed ready')
                time.sleep(0.5)
        finally:
            inside(first, f"import os,signal,json;os.kill({child_pid},signal.SIGCONT);print(json.dumps(True))")
        recovered = await_ready(first, 30)
        assert recovered['child_pid'] == child_pid
        result['health_recovery'] = 'hung-api-detected-and-recovered-without-restart'
        result['packages_before'] = inside(first, FINGERPRINT)
        status_report = cli(first, 'env', 'status')
        assert status_report['ok'], status_report['problems']
        assert status_report['diagnostic_uid'] == 1000
        assert status_report['diagnostic_python'] == '/opt/comfyctl/venv'
        assert status_report['environments']['tools']['origins']['torch'] is None
        expected_hub = locked_versions(ROOT / 'locks/tools/requirements.txt')['huggingface-hub']
        assert status_report['environments']['tools']['versions']['huggingface-hub'] == expected_hub
        assert status_report['environments']['host']['versions']['huggingface-hub'] != expected_hub
        result['cli_status'] = status_report
        result['cli_doctor'] = cli(first, 'env', 'doctor', '--deep')
        assert result['cli_doctor']['ok'], result['cli_doctor']['problems']
        if args.live_downloads:
            receipts = cli(first, 'model', 'sync', '/opt/runtime/provider-fixtures.yaml')
            verified = cli(first, 'model', 'status', '--verify')
            assert len(receipts) == len(verified) == 2
            assert all(item['status'] == 'verified' for item in verified)
            owners = inside(first, "import json;from pathlib import Path;print(json.dumps({str(p.relative_to('/workspace/storage/models')):p.stat().st_uid for p in Path('/workspace/storage/models').rglob('provider-smoke*') if p.is_file()}))")
            assert len(owners) == 2 and set(owners.values()) == {1000}
            result['public_model_cli'] = {'receipts': receipts, 'verified': verified, 'owners': owners,
                                          'scope': 'Public pinned files only; gated/private credentials not certified'}
        boundary = 'runtime-upload-boundary'
        body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="image"; filename="runtime.png"\r\nContent-Type: image/png\r\n\r\n').encode() + png() + ('\r\n--' + boundary + '--\r\n').encode()
        upload = urllib.request.Request(base + '/upload/image', data=body, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urllib.request.urlopen(upload, timeout=10) as response:
            assert json.load(response)['name'] == 'runtime.png'
        graph = {'1': {'class_type': 'ComfyctlRuntimeProbe', 'inputs': {}},
                 '2': {'class_type': 'PreviewAny', 'inputs': {'source': ['1', 0]}}}
        entry = execute(base, graph, args.timeout)
        paths = json.loads(entry['outputs']['2']['text'][0])
        assert paths['worker_stopped']
        assert paths['host']['uid'] == paths['worker']['uid'] == 1000
        assert paths['host']['pid'] != paths['worker']['pid']
        for field in ['base', 'models', 'input', 'output', 'user', 'temp', 'custom_nodes', 'checkpoint_paths', 'marker', 'input_files']:
            assert paths['host'][field] == paths['worker'][field], (field, paths)
        assert paths['host']['models'] == '/workspace/storage/models'
        assert paths['host']['marker'] == 'model-path-marker'
        assert 'runtime.png' in paths['worker']['input_files']
        result['paths'] = paths
        core = {'1': {'class_type': 'EmptyImage', 'inputs': {'width': 64, 'height': 64, 'batch_size': 1, 'color': 123}},
                '2': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0], 'filename_prefix': 'runtime-output'}}}
        result['core_output'] = execute(base, core, args.timeout)['outputs']['2']['images'][0]
        result['permissions'] = inside(first, """import json,os
from pathlib import Path
result={}
for name in ['/opt/runtime/venv/lib/python3.11/site-packages/torch/version.py','/opt/workers/depthanythingv3-nodes/worker-lock.json','/opt/probe/ComfyUI/main.py']:
    try:
        with open(name,'ab'):pass
        raise RuntimeError('Service could write protected path: '+name)
    except (PermissionError,OSError):result[name]='write-rejected'
result['pid1_status']=[line for line in Path('/proc/1/status').read_text().splitlines() if line.startswith(('Uid:','NoNewPrivs:'))]
import psutil
result['metadata_workers']=[{'pid':p.pid,'python':p.cmdline()[0],
    'cpu':p.environ().get('COMFY_CPU'),'cuda_visible_devices':p.environ().get('CUDA_VISIBLE_DEVICES')}
    for p in psutil.Process(1).children(recursive=True)
    if any('persistent_worker.py' in arg for arg in p.cmdline()) and p.environ().get('COMFYCTL_METADATA_WORKER')=='1']
result['prefix_metadata_cache_files']=len(list(Path('/opt/workers').glob('*/.metadata_cache.pkl')))
print(json.dumps(result))""")
        assert any(line.split()[1:] == ['1000'] * 4 for line in result['permissions']['pid1_status'] if line.startswith('Uid:'))
        assert 'NoNewPrivs:\t1' in result['permissions']['pid1_status']
        assert len(result['permissions']['metadata_workers']) == 5
        assert all(row['cpu']=='1' and row['cuda_visible_devices']=='' and row['python'].startswith('/opt/workers/')
                   for row in result['permissions']['metadata_workers'])
        assert result['permissions']['prefix_metadata_cache_files'] == 0
        assert result['packages_before'] == inside(first, FINGERPRINT)
        sam_graph = json.loads((ROOT / 'tests/workflows/sam3-points-cpu.json').read_text())
        da_graph = json.loads((ROOT / 'tests/workflows/da3-camera-cpu.json').read_text())
        result['sam3_native'] = points(execute(base, sam_graph, args.timeout), 0.25)
        result['da3_native_status'] = execute(base, da_graph, args.timeout)['status']['status_str']
        native = {Path(row['cmd'][0]).parent.parent.name: row for row in inside(first, PROCESSES)}
        assert set(native) == {'sam3-nodes', 'depthanythingv3-nodes'}
        assert all(row['cpu_mode'] == '1' and row['attention_policy'] == 'pytorch' for row in native.values())
        uids = inside(first, 'import json,psutil;print(json.dumps({str(pid):psutil.Process(pid).uids().effective for pid in ' + repr([row['pid'] for row in native.values()]) + '}))')
        assert set(uids.values()) == {1000}
        result['native_workers_before_shutdown'] = {name: {'pid': row['pid'], 'uid': uids[str(row['pid'])]} for name, row in native.items()}
        corrupt_file.write_text(docker('exec', '--user', '1000:1000', first, 'cat', '/opt/runtime/venv/lib/python3.11/site-packages/torch/version.py') + '\n# injected file drift with unchanged version metadata\n')
        docker('stop', '--time', '25', first)
        assert json.loads(docker('inspect', first))[0]['State']['ExitCode'] == 0
        second = launch('-restart', offline=True)
        result['restart_ready_without_network'] = await_ready(second, args.timeout)
        result['persisted'] = inside(second, "import json;from pathlib import Path;r=Path('/workspace/storage');print(json.dumps({'user':(r/'user/persistence.txt').read_text(),'model':(r/'models/checkpoints/runtime-marker.safetensors').read_text(),'input':(r/'input/runtime.png').is_file(),'output':len(list((r/'output').glob('runtime-output*.png')))}))")
        assert result['persisted'] == {'user': 'keep-me', 'model': 'model-path-marker', 'input': True, 'output': 1}
        assert 'Live CPU metadata:' in docker('logs', second)
        assert result['packages_before'] == inside(second, FINGERPRINT)
        docker('stop', '--time', '25', second)
        assert json.loads(docker('inspect', second))[0]['State']['ExitCode'] == 0
        drifted = launch('-drift', offline=True, corrupt=True)
        await_ready(drifted, args.timeout)
        same_versions = cli(drifted, 'env', 'status')
        assert all(not any(report['drift'].values()) for report in same_versions['environments'].values())
        drift_report = cli(drifted, 'env', 'doctor', '--deep', expected=2)
        assert 'host:file-drift' in drift_report['problems']
        assert any(row['path'].endswith('/torch/version.py') for row in drift_report['environments']['host']['record_hashes']['mismatches'])
        result['file_drift_injection'] = {'unchanged_versions': True, 'problems': drift_report['problems'],
                                         'host_hash_mismatches': drift_report['environments']['host']['record_hashes']['mismatches']}
        docker('stop', '--time', '25', drifted)
        broken = launch('-failure', offline=True, invalid=True)
        deadline = time.monotonic() + 30
        while json.loads(docker('inspect', broken))[0]['State']['Running']:
            if time.monotonic() > deadline:
                raise RuntimeError('Invalid launch did not stop')
            time.sleep(0.5)
        broken_state = json.loads(docker('inspect', broken))[0]['State']
        assert broken_state['ExitCode'] != 0
        # Read persisted state using a short-lived service-account diagnostic container.
        final = json.loads(docker('run', '--rm', '--platform', 'linux/amd64', '--user', '1000:1000', '--entrypoint', 'python', '--mount', 'type=volume,source=' + volume + ',target=/workspace,readonly', args.image, '-c', "print(open('/workspace/state/runtime-status.json').read())"))
        assert final['phase'] == 'recovery-required'
        result['failure_state'] = final
        result['shutdown'] = 'both-normal-runs-exited-zero'
        result['status'] = 'passed'
    finally:
        for container in containers:
            docker('rm', '--force', container)
        docker('volume', 'rm', volume)
        temporary.cleanup()
    result['containers_and_volume_removed'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'image_id': image_id, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
