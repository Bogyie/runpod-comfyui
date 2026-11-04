#!/usr/bin/env python3
"""Exercise prompt draining, explicit reload, rollback and interrupted journal recovery."""
import argparse
import json
import subprocess
import time
import urllib.error
import uuid
from pathlib import Path

from probe_host import ROOT, docker, request
from probe_runtime import await_ready, inside as run_inside, cli
from probe_workers import execute, points, PROCESSES, FINGERPRINT


def inside(container, expression):
    return run_inside(container, 'import json;from pathlib import Path;print(json.dumps(' + expression + '))')


def wait_for(container, expression, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if inside(container, expression):
            return
        time.sleep(0.1)
    raise RuntimeError('Live gate condition timed out: ' + expression)


def command(container, *arguments):
    return subprocess.Popen(['docker', 'exec', container, 'comfyctl', *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def complete(process, expected=0):
    stdout, stderr = process.communicate(timeout=600)
    if process.returncode != expected:
        raise RuntimeError('Unexpected live CLI outcome: ' + (stdout + stderr)[-8000:])
    return json.loads(stdout) if expected == 0 else stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='runpod-comfyui:probe-runtime-probe')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/evidence/live-transitions-cpu-probe.json')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    image_id = json.loads(docker('image', 'inspect', args.image))[0]['Id']
    token = uuid.uuid4().hex[:10]
    volume = 'comfy-live-volume-' + token
    docker('volume', 'create', volume)
    containers = []
    result = {'kind': 'live-state-only-transitions-cpu-gate', 'image_id': image_id,
              'scope': 'Real queued tasks and state-only generations; no new-node installation, Manager, GPU or network volume certification'}

    def launch(suffix):
        container = docker('run', '--detach', '--platform', 'linux/amd64', '--name', 'comfy-live-' + token + suffix,
                           '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m', '--shm-size', '512m',
                           '--mount', 'type=volume,source=' + volume + ',target=/workspace',
                           '--mount', 'type=bind,source=' + str(ROOT / 'tests/fixtures/live-probe-nodes') + ',target=/opt/probe/ComfyUI/custom_nodes/LiveGate,readonly',
                           '--publish', '127.0.0.1::8188', args.image, '--cpu', '--use-pytorch-cross-attention', '--listen', '0.0.0.0', '--port', '8188')
        containers.append(container)
        return container

    try:
        container = launch('-first')
        initial = await_ready(container, 300)
        port = json.loads(docker('inspect', container))[0]['NetworkSettings']['Ports']['8188/tcp'][0]['HostPort']
        base = 'http://127.0.0.1:' + port
        fingerprint = run_inside(container, FINGERPRINT)
        sam = json.loads((ROOT / 'tests/workflows/sam3-points-cpu.json').read_text())
        points(execute(base, sam, 240), 0.25)
        old_workers = run_inside(container, PROCESSES)
        disabled = cli(container, 'node', 'disable', 'itools', '--defer')['selection']['desired']
        for name, seconds in [('firstjob', 6), ('queuedjob', 2)]:
            request(base, '/prompt', {'prompt': {'1': {'class_type': 'ComfyctlLiveDelay', 'inputs': {'token': name, 'seconds': seconds}}}})
        wait_for(container, "Path('/workspace/state/live-jobs/firstjob.json').exists()")
        applying = command(container, 'env', 'apply', '--restart')
        wait_for(container, "Path('/workspace/runtime/control/maintenance.json').exists()")
        for route in ['/prompt', '/api/prompt']:
            try:
                request(base, route, {'prompt': {}})
                raise RuntimeError('Maintenance accepted a new prompt')
            except urllib.error.HTTPError as exc:
                assert exc.code == 503
        assert inside(container, "json.loads(Path('/workspace/state/runtime-status.json').read_text())['child_pid']") == initial['child_pid']
        switched = complete(applying)
        assert switched['live_transition'] == 'committed' and switched['new_child_pid'] != switched['old_child_pid']
        assert switched['selection']['desired'] == disabled
        assert 'iToolsCheckerBoard' not in request(base, '/object_info')
        jobs = inside(container, "{p.stem:json.loads(p.read_text()) for p in Path('/workspace/state/live-jobs').glob('*.json')}")
        assert all(jobs[name]['finished'] is not None for name in ['firstjob', 'queuedjob'])
        assert inside(container, "not Path('/workspace/runtime/control/maintenance.json').exists()")
        assert not inside(container, "__import__('psutil').pid_exists(" + str(initial['child_pid']) + ")")
        for worker in old_workers:
            assert not inside(container, "__import__('psutil').pid_exists(" + str(worker['pid']) + ")")
        result['drain_and_commit'] = {'transition': switched, 'jobs_finished': jobs, 'old_workers_reaped': len(old_workers), 'admission_status': 503}
        enabled = cli(container, 'node', 'enable', 'itools', '--defer')['selection']['desired']
        before = inside(container, "json.loads(Path('/workspace/state/runtime-status.json').read_text())['child_pid']")
        request(base, '/prompt', {'prompt': {'1': {'class_type': 'ComfyctlLiveDelay', 'inputs': {'token': 'timeoutjob', 'seconds': 4}}}})
        wait_for(container, "Path('/workspace/state/live-jobs/timeoutjob.json').exists()")
        error = complete(command(container, 'env', 'apply', '--restart', '--drain-timeout', '0.5'), expected=1)
        assert 'Drain timed out' in error
        assert inside(container, "json.loads(Path('/workspace/state/runtime-status.json').read_text())['child_pid']") == before
        wait_for(container, "json.loads(Path('/workspace/state/live-jobs/timeoutjob.json').read_text())['finished'] is not None")
        assert inside(container, "not Path('/workspace/runtime/control/maintenance.json').exists()")
        result['drain_timeout'] = 'work-completed-and-child-unchanged'
        # Corrupt only after selection and journal switch, to exercise automatic
        # rollback of a real partial transition rather than preflight rejection.
        watcher = """import json,time
from pathlib import Path
end=time.monotonic()+120
while time.monotonic()<end:
    path=Path('/workspace/runtime/control/transition.json')
    item=json.loads(path.read_text()) if path.exists() else {}
    if item.get('phase')=='switched' and item.get('target')==TARGET:
        Path('/workspace/runtime/generations/'+TARGET+'/ComfyUI/main.py').write_text('# injected corruption after pointer switch\\n')
        break
    time.sleep(0.01)
else:raise RuntimeError('Corruption watcher timed out')
"""
        docker('exec', '--detach', container, 'python', '-c', 'TARGET=' + repr(enabled) + '\n' + watcher)
        error = complete(command(container, 'env', 'apply', '--restart', '--startup-timeout', '120'), expected=1)
        assert 'preserved generation restored' in error
        state = await_ready(container, 180)
        assert state['generation_id'] == disabled
        assert inside(container, "json.loads(Path('/workspace/runtime/control/transition.json').read_text())['phase']") == 'rolled-back'
        assert inside(container, "not Path('/workspace/runtime/control/maintenance.json').exists()")
        result['failed_switch'] = 'automatic-rollback-confirmed'
        # A killed root controller leaves a durable uncommitted transaction.
        target = cli(container, 'node', 'enable', 'itools', '--defer')['selection']['desired']
        killer = """import json,time,os,signal
from pathlib import Path
end=time.monotonic()+120
while time.monotonic()<end:
    item=json.loads(Path('/workspace/runtime/control/transition.json').read_text())
    if item.get('phase')=='switched' and item.get('target')==TARGET:
        os.kill(item['controller_pid'],signal.SIGKILL)
        break
    time.sleep(0.01)
else:raise RuntimeError('Controller watcher timed out')
"""
        docker('exec', '--detach', container, 'python', '-c', 'TARGET=' + repr(target) + '\n' + killer)
        interrupted = command(container, 'env', 'apply', '--restart')
        interrupted.communicate(timeout=180)
        assert interrupted.returncode != 0
        assert inside(container, "Path('/workspace/runtime/control/maintenance.json').exists()")
        docker('stop', '--time', '25', container)
        recovered = launch('-recovered')
        state = await_ready(recovered, 300)
        assert state['generation_id'] == disabled
        assert inside(recovered, "json.loads(Path('/workspace/runtime/control/transition.json').read_text())['phase']") == 'recovered-on-boot'
        assert inside(recovered, "not Path('/workspace/runtime/control/maintenance.json').exists()")
        assert run_inside(recovered, FINGERPRINT) == fingerprint
        jobs_after = inside(recovered, "{p.stem:json.loads(p.read_text()) for p in Path('/workspace/state/live-jobs').glob('*.json')}")
        assert jobs_after == {**jobs, 'timeoutjob': jobs_after['timeoutjob']}
        result.update(status='passed', interrupted_controller='recovered-old-generation-on-boot', user_job_files_preserved=True,
                      package_fingerprint_unchanged=True, recovered_generation=disabled)
    finally:
        if result.get('status') != 'passed':
            logs = []
            for container in containers:
                process = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
                logs.append(process.stdout[-18000:] + process.stderr[-6000:])
            (ROOT / '.work/live-transition-failure.log').write_text('\n'.join(logs))
        for container in containers:
            docker('rm', '--force', container)
        docker('volume', 'rm', volume)
    result['containers_and_volume_removed'] = True
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'image_id': image_id}))


if __name__ == '__main__':
    main()
