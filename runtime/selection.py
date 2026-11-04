"""Durable, root-managed code/environment/node selection for one image identity."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

CONTROL = Path('/workspace/runtime/control')
GENERATIONS = Path('/workspace/runtime/generations')
BASELINE = Path('/opt/runtime/control/baseline.json')


class SelectionError(Exception):
    pass


def durable_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def code_hashes(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if '__pycache__' in path.parts or '.git' in path.parts:
            continue
        if path.is_symlink():
            raise SelectionError('Code snapshot contains a symlink: ' + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class Store:
    def __init__(self, control=CONTROL, generations=GENERATIONS, baseline=BASELINE):
        self.control = Path(control)
        self.generations = Path(generations)
        self.base = json.loads(Path(baseline).read_text())
        self.state_file = self.control / 'selection.json'

    @contextlib.contextmanager
    def locked(self):
        self.control.mkdir(parents=True, exist_ok=True)
        self.generations.mkdir(parents=True, exist_ok=True)
        if self.control.is_symlink() or self.generations.is_symlink():
            raise SelectionError('Control/generation roots may not be symlinks')
        with (self.control / 'selection.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def state(self):
        if not self.state_file.exists():
            return {'runtime_id': self.base['runtime_id'], 'desired': 'image-base',
                    'last_good': None, 'previous_good': None, 'revision': 0}
        state = json.loads(self.state_file.read_text())
        if not isinstance(state, dict) or not all(key in state for key in ['runtime_id', 'desired', 'last_good', 'previous_good', 'revision']):
            raise SelectionError('Selection state is malformed; use explicit env reset')
        if not isinstance(state['revision'], int) or state['revision'] < 0:
            raise SelectionError('Selection revision is malformed; use explicit env reset')
        if state['runtime_id'] != self.base['runtime_id']:
            raise SelectionError('Selection belongs to another image; use explicit env reset in recovery mode')
        return state

    def profile(self, identifier, verify=True):
        if identifier == 'image-base':
            return dict(self.base, id='image-base', validation={'kind': 'image-base'})
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise SelectionError('Invalid generation id')
        directory = self.generations / identifier
        if directory.is_symlink() or directory.resolve() != directory:
            raise SelectionError('Unsafe generation directory')
        profile = json.loads((directory / 'generation.json').read_text())
        if profile['id'] != identifier or profile['runtime_id'] != self.base['runtime_id']:
            raise SelectionError('Generation identity does not match this image')
        if profile['comfy_root'] != str(directory / 'ComfyUI'):
            raise SelectionError('Generation source is not at its final path')
        # State-only generations reuse immutable environments, never aliases or moved venvs.
        if profile['host_python'] != self.base['host_python'] or profile['workers'] != self.base['workers']:
            raise SelectionError('Unreviewed environment bindings in state-only generation')
        if set(profile['nodes']) != set(self.base['nodes']):
            raise SelectionError('State-only generation changed the managed node catalog')
        for name, node in profile['nodes'].items():
            if not isinstance(node['enabled'], bool) or any(node[key] != self.base['nodes'][name][key]
                    for key in ['directory', 'commit', 'required_nodes', 'lock_sha256']):
                raise SelectionError('Unreviewed node definition in state-only generation')
        if json.loads((directory / 'workers.json').read_text()) != profile['workers']:
            raise SelectionError('Generation worker mapping drift detected')
        if verify and code_hashes(directory / 'ComfyUI') != profile['files']:
            raise SelectionError('Generation code drift detected')
        return profile

    def desired(self):
        return self.profile(self.state()['desired'])

    def acknowledge(self, record, namespace, now=None):
        state = self.state()
        identifier = record.get('generation_id')
        try:
            age = (time.time() if now is None else now) - float(record.get('updated_at', 0))
        except (TypeError, ValueError):
            return state
        if (record.get('phase') == 'ready' and record.get('runtime_id') == self.base['runtime_id']
                and record.get('pid_namespace') == namespace and 0 <= age <= 45 and identifier):
            self.profile(identifier)
            if state['last_good'] != identifier:
                state['previous_good'] = state['last_good']
                state['last_good'] = identifier
                durable_json(self.state_file, state)
        return state

    def stage_node_state(self, name, enabled):
        parent = self.desired()
        matches = [key for key, item in parent['nodes'].items() if name in {key, item['directory']}]
        if len(matches) != 1:
            raise SelectionError('Unknown managed node: ' + name)
        node = matches[0]
        if parent['nodes'][node]['enabled'] == enabled:
            return parent, False
        source = Path(parent['comfy_root'])
        size = sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
        if shutil.disk_usage(self.generations).free < 2 * size + 512 * 1024 * 1024:
            raise SelectionError('Insufficient disk space to prepare a code generation')
        identifier = uuid.uuid4().hex
        directory = self.generations / identifier
        directory.mkdir(mode=0o755)
        destination = directory / 'ComfyUI'
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '.git'), symlinks=True)
        nodes = json.loads(json.dumps(parent['nodes']))
        item = nodes[node]
        old = item['directory'] + ('' if item['enabled'] else '.disabled')
        new = item['directory'] + ('' if enabled else '.disabled')
        (destination / 'custom_nodes' / old).rename(destination / 'custom_nodes' / new)
        item['enabled'] = enabled
        profile = {key: value for key, value in parent.items() if key not in {'files', 'validation'}}
        profile.update(id=identifier, parent=parent['id'], comfy_root=str(destination), nodes=nodes,
                       files=code_hashes(destination), validation=None)
        durable_json(directory / 'workers.json', profile['workers'])
        durable_json(directory / 'generation.json', profile)
        return profile, True

    def validated(self, profile, receipt):
        directory = self.generations / profile['id']
        profile = self.profile(profile['id'])
        profile['validation'] = receipt
        durable_json(directory / 'generation.json', profile)
        return profile

    def select(self, identifier):
        profile = self.profile(identifier)
        if not profile.get('validation'):
            raise SelectionError('Generation has not passed validation')
        state = self.state()
        state.update(desired=identifier, revision=state['revision'] + 1)
        durable_json(self.state_file, state)
        return state

    def rollback(self):
        state = self.state()
        targets = ([state['last_good'], state['previous_good']] if state['desired'] != state['last_good']
                   else [state['previous_good']])
        for target in targets:
            if target:
                try:
                    return self.select(target)
                except (SelectionError, OSError, ValueError, KeyError):
                    continue
        raise SelectionError('No intact preserved good generation is available; use env reset')

    def reset(self):
        if self.state_file.exists():
            raw = self.state_file.read_bytes()
            try:
                self.state()
            except (SelectionError, ValueError, KeyError, TypeError):
                archive = hashlib.sha256(raw).hexdigest()
                durable_json(self.control / ('previous-selection-' + archive + '.json'),
                             {'preserved_raw_state': raw.decode('utf-8', errors='replace')})
                self.state_file.unlink()
        return self.select('image-base')


def selected_environment():
    store = Store()
    profile = store.desired()
    env = {'COMFYCTL_COMFY_ROOT': profile['comfy_root'], 'COMFYCTL_GENERATION_ID': profile['id']}
    if profile['id'] != 'image-base':
        env['COMFYCTL_WORKER_MAP_FILE'] = str(store.generations / profile['id'] / 'workers.json')
    required = {'SaveImage'}
    for node in profile['nodes'].values():
        if node['enabled']:
            required.update(node['required_nodes'])
    return env, required
