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
        from image_state import ImageHistory
        self.images = ImageHistory(self.control,self.base)

    def write_state(self, state):
        if self.images.enabled:
            state['compatibility_id'] = self.images.key
        durable_json(self.state_file,state)
        self.images.save(state)

    def prepare_image(self):
        transaction = self.pending_transition()
        if transaction and transaction.get('compatibility_id',transaction['runtime_id']) != self.images.key:
            raise SelectionError('Interrupted transition belongs to another execution environment; recover the previous image first')
        self.images.prepare(self.state_file)

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
            result = {'runtime_id': self.base['runtime_id'], 'desired': 'image-base',
                      'last_good': None, 'previous_good': None, 'revision': 0}
            if self.images.enabled:result['compatibility_id']=self.images.key
            return result
        state = json.loads(self.state_file.read_text())
        if not isinstance(state, dict) or not all(key in state for key in ['runtime_id', 'desired', 'last_good', 'previous_good', 'revision']):
            raise SelectionError('Selection state is malformed; use explicit env reset')
        if not isinstance(state['revision'], int) or state['revision'] < 0:
            raise SelectionError('Selection revision is malformed; use explicit env reset')
        if state['runtime_id'] != self.base['runtime_id'] or (self.images.enabled and state.get('compatibility_id')!=self.images.key):
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
        compatible = (profile.get('compatibility_id')==self.images.key if self.images.enabled
                      else profile['runtime_id']==self.base['runtime_id'])
        if profile['id'] != identifier or not compatible:
            raise SelectionError('Generation identity does not match this image')
        if self.images.enabled and any(profile.get(key)!=self.base[key] for key in ['abi_id','environment_id','application_id']):
            raise SelectionError('Generation execution contract differs from this image')
        if profile['comfy_root'] != str(directory / 'ComfyUI'):
            raise SelectionError('Generation source is not at its final path')
        managed = profile.get('kind') == 'managed-nodes-v1'
        if profile.get('kind') not in {None, 'managed-nodes-v1'}:
            raise SelectionError('Unknown generation kind')
        if profile['host_python'] != self.base['host_python']:
            raise SelectionError('Unreviewed host environment binding')
        if not managed and profile['workers'] != self.base['workers']:
            raise SelectionError('Unreviewed environment bindings in state-only generation')
        if (set(profile['nodes']) != set(self.base['nodes']) if not managed else not set(self.base['nodes']).issubset(profile['nodes'])):
            raise SelectionError('Generation changed the image node catalog')
        for name, original in self.base['nodes'].items():
            node = profile['nodes'][name]
            if not isinstance(node['enabled'], bool) or set(node) != set(original) or any(node[key] != value
                    for key, value in original.items() if key != 'enabled'):
                raise SelectionError('Unreviewed node definition in state-only generation')
        if managed:
            self.verify_managed(profile, verify)
        if json.loads((directory / 'workers.json').read_text()) != profile['workers']:
            raise SelectionError('Generation worker mapping drift detected')
        if verify and code_hashes(directory / 'ComfyUI') != profile['files']:
            raise SelectionError('Generation code drift detected')
        return profile

    def verify_managed(self, profile, verify):
        import re
        bindings = profile.get('environment_bindings', {})
        extras = set(profile['workers']) - self.base['workers'].keys()
        if set(bindings) != extras or any(profile['workers'].get(k) != v for k, v in self.base['workers'].items()):
            raise SelectionError('Managed generation changed image worker bindings')
        used, directories = set(), {item['directory'] for item in self.base['nodes'].values()}
        for key in profile['nodes'].keys() - self.base['nodes'].keys():
            node = profile['nodes'][key]
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', key) or not isinstance(node.get('enabled'), bool):
                raise SelectionError('Invalid added node identity/state')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', node.get('directory', '')) or node['directory'] in directories:
                raise SelectionError('Added node directory collides or is unsafe')
            directories.add(node['directory'])
            if self.base.get('generation_schema',1)>=2:
                archive=Path(node.get('source_archive',''))
                if (not archive.is_absolute() or archive.parent.parent!=self.generations or
                        not re.fullmatch(r'[0-9a-f]{32}',archive.parent.name) or archive.name!='source-'+key+'.tar.gz' or
                        archive.is_symlink() or archive.resolve()!=archive or not archive.is_file() or
                        archive.stat().st_uid!=0 or archive.stat().st_mode & 0o022):
                    raise SelectionError('Added node source archive is missing or unsafe')
                if verify and hashlib.sha256(archive.read_bytes()).hexdigest()!=node.get('archive_sha256'):
                    raise SelectionError('Added node source archive drift detected')
                smoke=node.get('smoke_workflow')
                if (not isinstance(smoke,dict) or not smoke or
                        hashlib.sha256(json.dumps(smoke,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=node.get('smoke_workflow_sha256')):
                    raise SelectionError('Added node smoke workflow drift detected')
            if (not re.fullmatch(r'[0-9a-f]{40}', node.get('commit', '')) or
                    any(not re.fullmatch(r'[0-9a-f]{64}', node.get(field, '')) for field in ['archive_sha256', 'source_plan_sha256', 'lock_sha256']) or
                    node.get('install_mode') not in {'native', 'adapter'} or not isinstance(node.get('required_nodes'), list) or not node['required_nodes'] or
                    not all(isinstance(v, str) and v for v in node['required_nodes']) or
                    not isinstance(node.get('environment_keys'), list) or not node['environment_keys'] or not set(node['environment_keys']).issubset(bindings) or
                    not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', node.get('repository', ''))):
                raise SelectionError('Added node provenance/environment definition is malformed')
            used.update(node['environment_keys'])
            plan = dict(node.get('source_plan', {}))
            recorded = plan.pop('plan_sha256', None)
            if (recorded != node['source_plan_sha256'] or hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != recorded or
                    plan.get('repository') != node['repository'] or plan.get('commit') != node['commit'] or plan.get('archive_sha256') != node['archive_sha256']):
                raise SelectionError('Added node source analysis identity drift detected')
            for env in node['environment_keys']:
                if bindings[env]['lock_sha256'] != node['lock_sha256']:
                    raise SelectionError('Added node lock and environment disagree')
        if used != extras:
            raise SelectionError('Unreferenced candidate environment binding')
        checked = set()
        for name, binding in bindings.items():
            prefix = Path(profile['workers'][name])
            if (not prefix.is_absolute() or len(prefix.parents) < 3 or prefix.name != 'venv' or prefix.parents[2] != self.generations or
                    not re.fullmatch(r'[0-9a-f]{32}', prefix.parents[1].name) or prefix.resolve() != prefix):
                raise SelectionError('Candidate environment is not at a managed final prefix')
            root = prefix.parent
            receipt_data = (root / 'receipt.json').read_bytes()
            receipt = json.loads(receipt_data)
            manifest_data = (root / 'sealed-files.json').read_bytes()
            if (hashlib.sha256(receipt_data).hexdigest() != binding['receipt_sha256'] or
                    hashlib.sha256(manifest_data).hexdigest() != receipt['sealed_files_sha256'] or
                    receipt['prefix'] != str(prefix) or receipt['lock_sha256'] != binding['lock_sha256'] or
                    receipt['gpu_lock_sha256'] != self.base['gpu_lock_sha256'] or
                    hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest() != receipt['lock_sha256'] or
                    prefix.stat().st_uid != 0 or prefix.stat().st_mode & 0o022):
                raise SelectionError('Candidate environment receipt/lock/seal drift detected')
            if verify and prefix not in checked:
                from environment_manifest import snapshot
                if snapshot(prefix) != json.loads(manifest_data):
                    raise SelectionError('Candidate environment file drift detected')
            checked.add(prefix)

    def fork_code(self, parent=None):
        parent = self.desired() if parent is None else parent
        source = Path(parent['comfy_root'])
        size = sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
        if shutil.disk_usage(self.generations).free < 2 * size + 512 * 1024 * 1024:
            raise SelectionError('Insufficient disk space to prepare a code generation')
        identifier = uuid.uuid4().hex
        directory = self.generations / identifier
        directory.mkdir(mode=0o755)
        destination = directory / 'ComfyUI'
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '.git'), symlinks=True)
        profile = json.loads(json.dumps(parent))
        profile.update(id=identifier, parent=parent['id'], comfy_root=str(destination), validation=None,
                       runtime_id=self.base['runtime_id'])
        profile.pop('files', None)
        return profile

    def save_candidate(self, profile):
        directory = self.generations / profile['id']
        profile['files'] = code_hashes(Path(profile['comfy_root']))
        durable_json(directory / 'workers.json', profile['workers'])
        durable_json(directory / 'generation.json', profile)
        return self.profile(profile['id'])

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
                self.write_state(state)
        return state

    def stage_node_state(self, name, enabled):
        parent = self.desired()
        matches = [key for key, item in parent['nodes'].items() if name in {key, item['directory']}]
        if len(matches) != 1:
            raise SelectionError('Unknown managed node: ' + name)
        node = matches[0]
        if parent['nodes'][node]['enabled'] == enabled:
            return parent, False
        profile = self.fork_code(parent)
        destination = Path(profile['comfy_root'])
        nodes = profile['nodes']
        item = nodes[node]
        old = item['directory'] + ('' if item['enabled'] else '.disabled')
        new = item['directory'] + ('' if enabled else '.disabled')
        (destination / 'custom_nodes' / old).rename(destination / 'custom_nodes' / new)
        item['enabled'] = enabled
        return self.save_candidate(profile), True

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
        self.write_state(state)
        return state

    def rollback_target(self):
        state = self.state()
        targets = ([state['last_good'], state['previous_good']] if state['desired'] != state['last_good']
                   else [state['previous_good']])
        for target in targets:
            if target:
                try:
                    profile = self.profile(target)
                    if profile.get('validation'):
                        return target
                except (SelectionError, OSError, ValueError, KeyError):
                    continue
        raise SelectionError('No intact preserved good generation is available; use env reset')

    def rollback(self):
        return self.select(self.rollback_target())

    def transition(self):
        path = self.control / 'transition.json'
        return json.loads(path.read_text()) if path.exists() else None

    def pending_transition(self):
        item = self.transition()
        return item if item and item['phase'] not in {'committed', 'rolled-back', 'cancelled', 'recovered-on-boot'} else None

    def begin_live(self, target, old_generation):
        if self.pending_transition():
            raise SelectionError('Unfinished live transition; restart the container to recover it')
        profile = self.profile(target)
        if not profile.get('validation'):
            raise SelectionError('Live target has not passed validation')
        transaction = {'id': uuid.uuid4().hex, 'phase': 'draining', 'target': target,
                       'old_generation': old_generation, 'before_state': self.state(),
                       'runtime_id': self.base['runtime_id'], 'pid_namespace': os.readlink('/proc/self/ns/pid'), 'controller_pid': os.getpid()}
        if self.images.enabled:transaction['compatibility_id']=self.images.key
        durable_json(self.control / 'transition.json', transaction)
        durable_json(self.control / 'maintenance.json', {'transaction_id': transaction['id']})
        return transaction

    def transition_phase(self, transaction, phase):
        transaction = dict(transaction, phase=phase)
        durable_json(self.control / 'transitions' / (transaction['id'] + '.json'), transaction)
        durable_json(self.control / 'transition.json', transaction)
        return transaction

    def restore_transition(self, transaction):
        if transaction.get('compatibility_id',transaction['runtime_id']) != self.images.key:
            raise SelectionError('Interrupted transition belongs to another image')
        before = transaction['before_state']
        for target in [transaction['old_generation'], before['last_good'], before['previous_good'], 'image-base']:
            if target:
                try:
                    profile = self.profile(target)
                    if profile.get('validation'):
                        state = dict(before, runtime_id=self.base['runtime_id'], desired=target, revision=before['revision'] + 2)
                        self.write_state(state)
                        return target
                except (SelectionError, OSError, ValueError, KeyError):
                    pass
        raise SelectionError('No intact environment available for interrupted transition recovery')

    def finish_live(self, transaction, phase):
        self.transition_phase(transaction, phase)
        flag = self.control / 'maintenance.json'
        if flag.exists() and json.loads(flag.read_text()).get('transaction_id') == transaction['id']:
            flag.unlink()

    def recover_interrupted(self):
        transaction = self.transition()
        if not transaction:
            return
        if self.pending_transition():
            self.restore_transition(transaction)
            self.finish_live(transaction, 'recovered-on-boot')
        else:
            self.finish_live(transaction, transaction['phase'])

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
    env = {'COMFYCTL_COMFY_ROOT': profile['comfy_root'], 'COMFYCTL_GENERATION_ID': profile['id'], 'COMFYCTL_HOST_PYTHON': profile['host_python']}
    if profile['id'] != 'image-base':
        env['COMFYCTL_WORKER_MAP_FILE'] = str(store.generations / profile['id'] / 'workers.json')
    required = {'SaveImage'}
    for node in profile['nodes'].values():
        if node['enabled']:
            required.update(node['required_nodes'])
    env['COMFYCTL_REQUIRED_ENDPOINTS'] = json.dumps(sorted({path for node in profile['nodes'].values() if node['enabled'] for path in node.get('required_endpoints', [])}))
    return env, required
