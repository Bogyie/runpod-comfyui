#!/usr/bin/env python3
"""Exercise real deferred node-state generations, rollback/reset and damaged boot recovery."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, inside, cli
from probe_workers import execute, points, PROCESSES, FINGERPRINT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/evidence/generations-cpu-probe.json')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    image_id = json.loads(docker('image', 'inspect', args.image))[0]['Id']
    token = uuid.uuid4().hex[:10]
    volume = 'comfy-generation-volume-' + token
    docker('volume', 'create', volume)
    containers = []
    result = {'image_id': image_id, 'kind': 'deferred-generation-lifecycle-cpu-gate',
              'scope': 'Known default node enable/disable and unchanged image environments; no new-node installation, live queue switching, Manager, GPU or network-volume certification'}

    def launch(suffix):
        container = docker('run', '--detach', '--platform', 'linux/amd64', '--name', 'comfy-generation-' + token + suffix,
                           '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m', '--shm-size', '512m',
                           '--mount', 'type=volume,source=' + volume + ',target=/workspace',
                           '--publish', '127.0.0.1::8188', args.image, '--cpu', '--use-pytorch-cross-attention',
                           '--listen', '0.0.0.0', '--port', '8188')
        containers.append(container)
        return container

    def ready(container, enabled):
        state = await_ready(container, 300)
        port = json.loads(docker('inspect', container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base = 'http://127.0.0.1:' + port
        assert ('iToolsCheckerBoard' in request(base, '/object_info')) == enabled
        return state, base

    def stop(container):
        docker('stop', '--time', '25', container)
        assert json.loads(docker('inspect', container))[0]['State']['ExitCode'] == 0

    def persisted(container):
        return inside(container, "import json;from pathlib import Path;print(json.dumps(Path('/workspace/storage/user/generation-sentinel.txt').read_text()))")

    try:
        first = launch('-base')
        initial, base = ready(first, True)
        assert initial['generation_id'] == 'image-base'
        inside(first, "import json;from pathlib import Path;Path('/workspace/storage/user/generation-sentinel.txt').write_text('preserve-across-generations');print(json.dumps(True))")
        fingerprint = inside(first, FINGERPRINT)
        disabled = cli(first, 'node', 'disable', 'itools', '--defer')
        identifier = disabled['selection']['desired']
        assert identifier != 'image-base' and disabled['restart_required'] and not disabled['applied_to_running_process']
        assert 'iToolsCheckerBoard' in request(base, '/object_info')
        status = cli(first, 'env', 'status')
        assert status['generation']['active'] == 'image-base' and status['generation']['desired'] == identifier
        repeated = cli(first, 'node', 'disable', 'itools', '--defer')
        assert repeated['selection']['desired'] == identifier
        denied = subprocess.run(['docker', 'exec', '--user', '1000:1000', first, 'comfyctl', 'env', 'reset', '--defer'], capture_output=True, text=True)
        assert denied.returncode == 1
        permissions = inside(first, """import os,json
from pathlib import Path
result={}
try:Path('/workspace/runtime/control/selection.json').write_text('tamper')
except OSError:result['control_write']='rejected'
else:raise RuntimeError('Service could change selection')
try:os.rename('/workspace/runtime','/workspace/runtime-unauthorized')
except OSError:result['control_rename']='rejected'
else:
    os.rename('/workspace/runtime-unauthorized','/workspace/runtime')
    raise RuntimeError('Service could replace control root')
print(json.dumps(result))""")
        stop(first)
        second = launch('-disabled')
        state, base = ready(second, False)
        assert state['generation_id'] == identifier
        sam_graph = json.loads((ROOT / 'tests/workflows/sam3-points-cpu.json').read_text())
        da_graph = json.loads((ROOT / 'tests/workflows/da3-camera-cpu.json').read_text())
        result['sam3_in_generation'] = points(execute(base, sam_graph, 240), 0.25)
        assert execute(base, da_graph, 240)['status']['status_str'] == 'success'
        result['worker_processes'] = inside(second, PROCESSES)
        assert all(row['cmd'][0].startswith('/opt/workers/') for row in result['worker_processes'])
        assert inside(second, FINGERPRINT) == fingerprint
        enabled = cli(second, 'node', 'enable', 'itools', '--defer')
        assert enabled['selection']['desired'] != identifier
        assert enabled['selection']['last_good'] == identifier
        assert 'iToolsCheckerBoard' not in request(base, '/object_info')
        pending_rollback = cli(second, 'env', 'rollback', '--defer')
        assert pending_rollback['selection']['desired'] == identifier
        reset = cli(second, 'env', 'reset', '--defer')
        assert reset['selection']['desired'] == 'image-base'
        assert persisted(second) == 'preserve-across-generations'
        stop(second)
        third = launch('-reset')
        state, base = ready(third, True)
        assert state['generation_id'] == 'image-base'
        rollback = cli(third, 'env', 'rollback', '--defer')
        assert rollback['selection']['desired'] == identifier
        assert rollback['selection']['previous_good'] == identifier
        stop(third)
        fourth = launch('-rollback')
        state, base = ready(fourth, False)
        assert state['generation_id'] == identifier and persisted(fourth) == 'preserve-across-generations'
        cli(fourth, 'node', 'disable', 'itools', '--defer')  # Acknowledge the actual healthy rollback boot.
        generation_path = '/workspace/runtime/generations/' + identifier
        snapshot = inside(fourth, "import json;from pathlib import Path;print(Path('" + generation_path + "/generation.json').read_text())")
        assert snapshot['validation']['core_graph'] == 'passed'
        assert snapshot['host_python'] == '/opt/runtime/venv/bin/python'
        assert all(value.startswith('/opt/workers/') for value in snapshot['workers'].values())
        docker('exec', '--user', '0:0', fourth, 'python', '-c', "from pathlib import Path;Path('" + generation_path + "/ComfyUI/main.py').write_text('# injected corruption after validation\\n')")
        stop(fourth)
        broken = launch('-damaged')
        deadline = time.monotonic() + 30
        while json.loads(docker('inspect', broken))[0]['State']['Running']:
            if time.monotonic() > deadline:
                raise RuntimeError('Damaged generation did not fail before boot')
            time.sleep(0.5)
        assert json.loads(docker('inspect', broken))[0]['State']['ExitCode'] != 0
        logs = subprocess.run(['docker', 'logs', broken], text=True, capture_output=True, check=True)
        assert 'Generation code drift detected' in logs.stdout + logs.stderr
        recovery = json.loads(docker('run', '--rm', '--platform', 'linux/amd64',
                                     '--mount', 'type=volume,source=' + volume + ',target=/workspace',
                                     args.image, 'comfyctl', 'env', 'rollback', '--defer'))
        assert recovery['selection']['desired'] == 'image-base'
        final = launch('-recovered')
        state, base = ready(final, True)
        assert state['generation_id'] == 'image-base'
        assert persisted(final) == 'preserve-across-generations'
        assert inside(final, FINGERPRINT) == fingerprint
        stop(final)
        result.update(status='passed', disabled_generation=identifier, permissions=permissions,
                      disabled_boot_persisted=True, unchanged_environment_bindings=snapshot['workers'],
                      validation=snapshot['validation'], enable_candidate_validated=enabled['selection']['desired'],
                      pending_rollback=pending_rollback['selection'], reset=reset['selection'],
                      previous_good_rollback=rollback['selection'], corruption_rejected_before_boot=True,
                      offline_recovery=recovery['selection'], user_data_preserved=True, package_fingerprint=fingerprint)
    finally:
        if result.get('status') != 'passed':
            for container in containers:
                if json.loads(docker('inspect', container))[0]['State']['Running']:
                    try:
                        logs = docker('exec', container, 'python', '-c', "from pathlib import Path;print('\\n'.join(str(p)+'\\n'+p.read_text()[-12000:] for p in Path('/workspace/runtime/generations').glob('*/validation.log')))")
                        (ROOT / '.work/generations-failure.log').write_text(logs)
                    except subprocess.CalledProcessError:
                        pass
        for container in containers:
            docker('rm', '--force', container)
        docker('volume', 'rm', volume)
    result['containers_and_volume_removed'] = True
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'image_id': image_id}))


if __name__ == '__main__':
    main()
