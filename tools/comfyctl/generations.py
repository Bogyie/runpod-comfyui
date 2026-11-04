"""Root-only staging and deferred selection; never mutate a running environment."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, '/opt/runtime/control')
from selection import Store, SelectionError


def read_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def validate(store, profile):
    directory = store.generations / profile['id']
    required = {'SaveImage'}
    for node in profile['nodes'].values():
        if node['enabled']:
            required.update(node['required_nodes'])
    with tempfile.TemporaryDirectory(prefix='validation-', dir='/workspace/state') as temporary:
        root = Path(temporary)
        os.chown(root, 1000, 1000)
        for name in ['models', 'input', 'output', 'user', 'temp', 'previews', 'cache', 'home', 'worker-tmp']:
            path = root / name
            path.mkdir()
            os.chown(path, 1000, 1000)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        env = dict(os.environ, COMFYCTL_COMFY_ROOT=profile['comfy_root'], COMFYCTL_GENERATION_ID=profile['id'],
                   COMFYCTL_WORKER_MAP_FILE=str(directory / 'workers.json'), COMFYCTL_STORAGE_DIR=str(root),
                   COMFYCTL_METADATA_CACHE=str(root / 'cache'), COMFY_ENV_ROOT=str(root / 'cache/workspace'),
                   HOME=str(root / 'home'), XDG_CACHE_HOME=str(root / 'cache'), HF_HOME=str(root / 'cache/hf'),
                   TORCH_HOME=str(root / 'cache/torch'), TMPDIR=str(root / 'worker-tmp'), COMFYCTL_RUNTIME_ID=profile['runtime_id'])
        with (directory / 'validation.log').open('w') as log:
            process = subprocess.Popen([profile['host_python'], '-I', '/opt/runtime/control/run_comfy.py', '--cpu',
                                        '--use-pytorch-cross-attention', '--listen', '127.0.0.1', '--port', str(port)],
                                       env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                       user=1000, group=1000, extra_groups=[])
            try:
                deadline = time.monotonic() + 300
                base = 'http://127.0.0.1:' + str(port)
                while True:
                    if process.poll() is not None:
                        raise SelectionError('Candidate startup failed; inspect ' + str(directory / 'validation.log'))
                    try:
                        objects = read_json(base + '/object_info')
                        if not required.issubset(objects):
                            raise SelectionError('Candidate is missing required nodes: ' + ','.join(sorted(required - objects.keys())) + '; inspect ' + str(directory / 'validation.log'))
                        break
                    except (OSError, TimeoutError):
                        if time.monotonic() > deadline:
                            raise SelectionError('Candidate startup timed out')
                        time.sleep(1)
                payload = {'prompt': {'1': {'class_type': 'EmptyImage', 'inputs': {'width': 64, 'height': 64, 'batch_size': 1, 'color': 0}},
                                      '2': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0], 'filename_prefix': 'candidate-check'}}}}
                request = urllib.request.Request(base + '/prompt', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=10) as response:
                    submitted = json.load(response)
                while True:
                    history = read_json(base + '/history/' + submitted['prompt_id'])
                    if submitted['prompt_id'] in history:
                        if history[submitted['prompt_id']]['status']['status_str'] != 'success':
                            raise SelectionError('Candidate core graph failed')
                        break
                    if time.monotonic() > deadline:
                        raise SelectionError('Candidate core graph timed out')
                    time.sleep(0.5)
                receipt = {'kind': 'state-only-candidate-cpu-validation', 'required_nodes': sorted(required),
                           'node_catalog': 'passed', 'core_graph': 'passed',
                           'environment_bindings': 'unchanged-image-prefixes', 'gpu': 'not-run', 'validated_at': time.time()}
            finally:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                except ProcessLookupError:
                    pass
    return store.validated(profile, receipt)


def operate(args):
    if os.geteuid() != 0:
        raise SelectionError('Generation mutation requires the container administrator (uid 0)')
    store = Store()
    with store.locked():
        from .environments import live_status
        try:
            record = json.loads(Path('/workspace/state/runtime-status.json').read_text())
        except (OSError, json.JSONDecodeError):
            record = {}
        healthy = live_status(record, store.base['runtime_id'])['healthy']
        if args.action != 'reset' and healthy:
            store.acknowledge(record, os.readlink('/proc/self/ns/pid'))
        if args.command == 'node':
            profile, changed = store.stage_node_state(args.name, args.action == 'enable')
            if changed:
                profile = validate(store, profile)
            state = store.select(profile['id'])
        elif args.action == 'rollback':
            state = store.rollback()
        else:
            state = store.reset()
        return {'selection': state, 'restart_required': not (healthy and record.get('generation_id') == state['desired']), 'applied_to_running_process': False,
                'scope': 'Deferred state-only generation; GPU/host/worker packages unchanged'}
