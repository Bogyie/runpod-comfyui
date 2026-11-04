"""Read-only environment diagnostics; candidate switching is a separate operation."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

CONTROL = Path('/opt/runtime/control')
WORKERS = Path('/opt/locks/workers')
INSPECT = Path(__file__).with_name('_inspect.py')


class EnvironmentError(Exception):
    pass


def locked_versions(path, marker_environment=None):
    result = {}
    for line in path.read_text().splitlines():
        if not re.match(r'^[A-Za-z0-9_.-]+==', line):
            continue
        req = Requirement(line.rstrip(' \\'))
        if req.marker and not req.marker.evaluate(marker_environment):
            continue
        spec = list(req.specifier)
        if len(spec) != 1 or spec[0].operator != '==':
            raise EnvironmentError('Diagnostic lock must contain exact versions')
        result[canonicalize_name(req.name)] = spec[0].version
    return result


def version_drift(actual, expected):
    actual = {canonicalize_name(k): v for k, v in actual.items()}
    return {'missing': sorted(expected.keys() - actual.keys()),
            'unexpected': sorted(actual.keys() - expected.keys()),
            'changed': {k: {'expected': v, 'actual': actual[k]} for k, v in expected.items() if k in actual and v != actual[k]}}


def live_status(record, runtime_id, now=None, namespace=None, proc=Path("/proc")):
    issues = []
    if not isinstance(record, dict):
        record = {}
        issues.append('invalid-state')
    if record.get('runtime_id') != runtime_id:
        issues.append('runtime-identity-mismatch')
    if namespace is None:
        try:
            namespace = os.readlink(proc / 'self/ns/pid')
        except OSError:
            issues.append('pid-namespace-unavailable')
    if record.get('pid_namespace') != namespace:
        issues.append('different-container')
    if record.get('phase') != 'ready':
        issues.append('not-ready')
    try:
        age = (time.time() if now is None else now) - float(record.get('updated_at', 0))
        if not math.isfinite(age):
            issues.append('invalid-heartbeat')
        elif age > 45 or age < -5:
            issues.append('stale-or-future-heartbeat')
    except (TypeError, ValueError):
        issues.append('invalid-heartbeat')
    try:
        pid = int(record['child_pid'])
        if pid <= 1 or b'/opt/runtime/control/run_comfy.py' not in (proc / str(pid) / 'cmdline').read_bytes().split(b'\x00'):
            issues.append('host-process-missing')
        uid = next(line for line in (proc / '1/status').read_text().splitlines() if line.startswith('Uid:'))
        if uid.split()[1:] != ['1000'] * 4:
            issues.append('supervisor-not-service-user')
    except (KeyError, OSError, ValueError, StopIteration):
        issues.append('host-process-missing')
    return {'healthy': not issues, 'issues': sorted(set(issues)), 'record': record}


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inspect_runtime(state, doctor=False, deep=False):
    try:
        identity = json.loads((CONTROL / 'identity.json').read_text())
        manifest = json.loads((WORKERS / 'manifest.json').read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        raise EnvironmentError('Runtime identity/worker manifest unavailable; run this command in the managed image') from None
    if hashlib.sha256(json.dumps(identity['inputs'], sort_keys=True).encode()).hexdigest() != identity['runtime_id']:
        raise EnvironmentError('Runtime identity is inconsistent')
    try:
        record = json.loads((state.parent / 'runtime-status.json').read_text())
    except (OSError, json.JSONDecodeError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    sys.path.insert(0, str(CONTROL))
    from selection import Store, SelectionError
    store = Store()
    try:
        selection = store.state()
        generation = {'active': record.get('generation_id'), 'desired': selection['desired'],
                      'last_known_good': selection['last_good'], 'previous_good': selection['previous_good'],
                      'candidate_switching_implemented': 'state-only-deferred-or-drained-restart',
                      'restart_required': record.get('generation_id') != selection['desired']}
    except (SelectionError, OSError, ValueError, KeyError) as exc:
        generation = {'error': str(exc), 'restart_required': True}
    result = {'runtime_id': identity['runtime_id'], 'diagnostic_uid': os.getuid(), 'diagnostic_python': sys.prefix,
              'generation': generation, 'scope': 'locked-versions-and-paths',
              'runtime': live_status(record, identity['runtime_id']), 'environments': {}, 'problems': []}
    if doctor and generation.get('active'):
        try:
            store.profile(generation['active'])
        except (SelectionError, OSError, ValueError, KeyError):
            result['problems'].append('active-generation-drift')
    if 'error' in generation:
        result['problems'].append('generation-selection-error')
    result['maintenance'] = (Path('/workspace/runtime/control/maintenance.json')).exists()
    if result['maintenance']:
        result['problems'].append('maintenance-active')
    if not result['runtime']['healthy']:
        result['problems'].append('runtime-not-healthy')
    definitions = {'host': (Path('/opt/runtime/venv'), Path('/opt/locks/host.txt')),
                   'tools': (Path('/opt/comfyctl/venv'), Path('/opt/locks/tools.txt'))}
    definitions.update({name: (Path('/opt/workers') / item['environment'], WORKERS / item['lock_file'])
                        for name, item in manifest['workers'].items()})
    hashes = {}
    for name, (prefix, lock) in definitions.items():
        report = {'prefix': str(prefix)}
        try:
            process = subprocess.run([str(prefix / 'bin/python'), '-I', str(INSPECT)], input=json.dumps({'deep': deep}),
                                     text=True, capture_output=True, check=True, timeout=60)
            snapshot = json.loads(process.stdout)
            rows = snapshot.pop('record_files')
            snapshot['versions'] = {canonicalize_name(k): v for k, v in snapshot['versions'].items()}
            expected = locked_versions(lock, snapshot.pop('marker_environment'))
            drift = version_drift(snapshot['versions'], expected)
            report.update(snapshot, drift=drift, lock_sha256=file_hash(lock))
            if snapshot['prefix'] != str(prefix):
                result['problems'].append(name + ':interpreter-prefix-mismatch')
            if name != 'host' and any(p.startswith('/opt/runtime/venv/') for p in snapshot['sys_path']):
                result['problems'].append(name + ':host-site-packages-leaked')
            if name == 'tools' and snapshot['origins']['torch'] is not None:
                result['problems'].append('tools:unexpected-GPU-package')
            if any(drift.values()):
                result['problems'].append(name + ':version-drift')
            if doctor:
                checked = subprocess.run(['/opt/runtime/venv/bin/uv', 'pip', 'check', '--python', str(prefix / 'bin/python')],
                                         capture_output=True, text=True, timeout=60,
                                         env=dict(os.environ, UV_CACHE_DIR='/workspace/cache/uv'))
                report['dependency_check'] = {'passed': checked.returncode == 0, 'output': (checked.stdout + checked.stderr)[-4000:]}
                if checked.returncode:
                    result['problems'].append(name + ':dependency-check-failed')
            if deep:
                mismatches = []
                for row in rows:
                    path = Path(row['path'])
                    if not any(path.is_relative_to(root) for root in [Path('/opt/runtime'), Path('/opt/workers'), Path('/opt/comfyctl')]):
                        mismatches.append({'path': row['path'], 'reason': 'record-path-escape'})
                        continue
                    if row['path'] not in hashes:
                        hashes[row['path']] = file_hash(path) if path.is_file() else None
                    if hashes[row['path']] != row['sha256']:
                        mismatches.append({'path': row['path'], 'package': row['package'], 'reason': 'hash-mismatch-or-missing'})
                report['record_hashes'] = {'checked_entries': len(rows), 'mismatches': mismatches}
                if mismatches:
                    result['problems'].append(name + ':file-drift')
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            report['error'] = type(exc).__name__
            result['problems'].append(name + ':inspection-failed')
        result['environments'][name] = report
    # Validate actual control/CLI code against the immutable build identity.
    code_drift = []
    for name, expected in identity['inputs'].items():
        if name == 'runtime/comfyctl':
            path = Path('/usr/local/bin/comfyctl')
        elif name == 'tools/rebuild/link_gpu_packages.py':
            path = CONTROL / 'gpu_links.py'
        elif name.startswith('runtime/') and name.endswith('.py'):
            path = CONTROL / Path(name).name
        elif name.startswith('tools/comfyctl/') and name.endswith('.py'):
            path = Path('/opt/comfyctl/src/comfyctl') / Path(name).relative_to('tools/comfyctl')
        else:
            continue
        if not path.is_file() or file_hash(path) != expected:
            code_drift.append(str(path))
    result['control_code_drift'] = code_drift
    if code_drift:
        result['problems'].append('control-code-drift')
    if doctor:
        try:
            port = int(record.get('port', 8188))
            if not 1 <= port <= 65535:
                raise ValueError('invalid port')
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/system_stats', timeout=5) as response:
                payload = json.load(response)
            result['api'] = {'healthy': 'system' in payload and 'devices' in payload}
        except Exception:
            result['api'] = {'healthy': False}
        if not result['api']['healthy']:
            result['problems'].append('api-unavailable')
    if deep:
        result['scope'] = 'locked-versions-paths-and-installed-RECORD-hashes-with-local-patch-overrides'
        result['unique_files_hashed'] = len(hashes)
    result['ok'] = not result['problems']
    return result
