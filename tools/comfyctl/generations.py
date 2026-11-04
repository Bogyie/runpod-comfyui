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


def refresh_record(previous, path=Path('/workspace/state/runtime-status.json')):
    try:
        current = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SelectionError('Runtime status unavailable after candidate preparation') from None
    for key in ['child_pid', 'generation_id', 'pid_namespace']:
        if previous.get(key) is not None and previous[key] != current.get(key):
            raise SelectionError('Running generation/process changed during candidate preparation; retry explicitly')
    return current


def validate(store, profile, smoke_workflow=None):
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
                   COMFYCTL_WORKER_MAP_FILE=str(directory / 'workers.json'), COMFYCTL_STORAGE_DIR=str(root), COMFYCTL_VALIDATING='1',
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
                        for name in profile['nodes'].keys() - store.base['nodes'].keys():
                            node = profile['nodes'][name]
                            if node['enabled'] and any(objects[item].get('python_module') != 'custom_nodes.' + node['directory'] for item in node['required_nodes']):
                                raise SelectionError('Added node catalog was supplied by another plugin')
                        for node in profile['nodes'].values():
                            if node['enabled']:
                                for path in node.get('required_endpoints', []):
                                    read_json(base + path)
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
                if smoke_workflow:
                    request = urllib.request.Request(base + '/prompt', data=json.dumps({'prompt': smoke_workflow}).encode(), headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(request, timeout=10) as response:
                        submitted = json.load(response)
                    if 'prompt_id' not in submitted or submitted.get('node_errors'):
                        raise SelectionError('Added-node smoke workflow failed validation')
                    while True:
                        history = read_json(base + '/history/' + submitted['prompt_id'])
                        if submitted['prompt_id'] in history:
                            if history[submitted['prompt_id']]['status']['status_str'] != 'success':
                                raise SelectionError('Added-node smoke workflow failed; inspect candidate validation log')
                            break
                        if time.monotonic() > deadline:
                            raise SelectionError('Added-node smoke workflow timed out')
                        time.sleep(0.5)
                    receipt.update(kind='managed-node-candidate-cpu-validation', environment_bindings='sealed-private-prefixes', smoke_workflow='passed')
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


def await_generation(target, runtime_id, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            record = json.loads(Path('/workspace/state/runtime-status.json').read_text())
            if record.get('runtime_id') != runtime_id:
                raise SelectionError('Runtime identity changed during transition')
            if record.get('generation_id') == target and record.get('phase') == 'ready':
                info = read_json(f'http://127.0.0.1:{port}/comfyctl/runtime/idle')
                if info['generation_id'] == target:
                    return record
            if record.get('phase') in {'recovery-required', 'stopped'} and (record.get('failed_generation') or record.get('generation_id')) == target:
                raise SelectionError('Selected generation failed to start')
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    raise SelectionError('Timed out waiting for selected generation readiness')


def live_select(store, target, record, args):
    from .environments import live_status
    if not live_status(record, store.base['runtime_id'])['healthy']:
        raise SelectionError('Live transition requires a healthy managed supervisor; use deferred recovery otherwise')
    if args.drain_timeout <= 0 or args.startup_timeout <= 0:
        raise SelectionError('Transition timeouts must be positive')
    if record['generation_id'] == target:
        state = store.select(target)
        return {'selection': state, 'restart_required': False, 'applied_to_running_process': False, 'live_transition': 'already-running'}
    transaction = store.begin_live(target, record['generation_id'])
    port = int(record['port'])
    switched = False
    try:
        deadline = time.monotonic() + args.drain_timeout
        while True:
            idle = read_json(f'http://127.0.0.1:{port}/comfyctl/runtime/idle')
            if idle['generation_id'] != record['generation_id']:
                raise SelectionError('Running generation changed during drain')
            if idle['running'] == idle['pending'] == idle['inflight'] == 0:
                break
            if time.monotonic() > deadline:
                raise SelectionError('Drain timed out; running work was left intact')
            time.sleep(0.25)
        store.select(target)
        switched = True
        transaction = store.transition_phase(transaction, 'switched')
        os.kill(1, signal.SIGUSR1)
        ready = await_generation(target, store.base['runtime_id'], port, args.startup_timeout)
        state = store.acknowledge(ready, os.readlink('/proc/self/ns/pid'))
        store.finish_live(transaction, 'committed')
        return {'selection': state, 'restart_required': False, 'applied_to_running_process': True,
                'live_transition': 'committed', 'old_child_pid': record['child_pid'], 'new_child_pid': ready['child_pid']}
    except Exception as error:
        if not switched:
            store.finish_live(transaction, 'cancelled')
            raise
        old = store.restore_transition(transaction)
        transaction = store.transition_phase(transaction, 'rollback-requested')
        os.kill(1, signal.SIGUSR1)
        try:
            await_generation(old, store.base['runtime_id'], port, args.startup_timeout)
        except SelectionError as rollback_error:
            raise SelectionError('Switch failed and rollback is unconfirmed; restart for journal recovery') from rollback_error
        store.finish_live(transaction, 'rolled-back')
        raise SelectionError('Switch failed; preserved generation restored: ' + str(error)) from error


def operate(args):
    if os.geteuid() != 0:
        raise SelectionError('Generation mutation requires the container administrator (uid 0)')
    store = Store()
    with store.locked():
        if store.pending_transition():
            raise SelectionError('Unfinished live transition; restart the container for journal recovery')
        from .environments import live_status
        try:
            record = json.loads(Path('/workspace/state/runtime-status.json').read_text())
        except (OSError, json.JSONDecodeError):
            record = {}
        healthy = live_status(record, store.base['runtime_id'])['healthy']
        if args.action != 'reset' and healthy:
            store.acknowledge(record, os.readlink('/proc/self/ns/pid'))
        if args.command == 'node':
            if args.action == 'add':
                from .node_install import stage_node
                profile, workflow = stage_node(store, args)
                profile = validate(store, profile, workflow)
            else:
                profile, changed = store.stage_node_state(args.name, args.action == 'enable')
                if changed:
                    profile = validate(store, profile)
            target = profile['id']
        elif args.action == 'rollback':
            target = store.rollback_target()
        elif args.action == 'apply':
            target = store.state()['desired']
        else:
            target = 'image-base'
        if getattr(args, 'restart', False):
            # Candidate installation/validation can outlive a heartbeat window.
            # Re-read it without accepting an unrelated replacement process.
            record = refresh_record(record)
            if args.action != 'reset' and live_status(record, store.base['runtime_id'])['healthy']:
                store.acknowledge(record, os.readlink('/proc/self/ns/pid'))
            return live_select(store, target, record, args)
        state = store.reset() if args.action == 'reset' else store.select(target)
        return {'selection': state, 'restart_required': not (healthy and record.get('generation_id') == state['desired']),
                'applied_to_running_process': False, 'scope': 'Validated deferred generation; existing image environments unchanged'}
