"""Plan or remove unreferenced generations while holding the selection lock."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time
import uuid

from selection import SelectionError, durable_json

ID = re.compile(r'[0-9a-f]{32}')


def process_references(root, record, proc=Path('/proc')):
    """Protect actual prefix users, including orphaned candidate installers."""
    references = set()
    pattern = re.compile(re.escape(os.fsencode(str(root))) + rb'/([0-9a-f]{32})(?:/|\x00|$)')
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / 'cmdline').read_bytes()
        except FileNotFoundError:
            continue
        references.update(m[1].decode() for m in pattern.finditer(command))
        if b'/opt/runtime/control/run_comfy.py' not in command:
            continue
        try:
            environment = (entry / 'environ').read_bytes().split(b'\x00')
        except FileNotFoundError:
            continue
        except PermissionError:
            # Some container roots cannot ptrace the service UID. Its durable
            # heartbeat identifies the main host; unidentified hosts block GC.
            if int(entry.name) == record.get('child_pid') and record.get('pid_namespace') == os.readlink('/proc/self/ns/pid'):
                references.add(record.get('generation_id'))
                continue
            raise SelectionError('Cannot identify a running managed host; generation cleanup refused') from None
        generation = next((value.split(b'=', 1)[1].decode() for value in environment if value.startswith(b'COMFYCTL_GENERATION_ID=')), None)
        if generation is None:
            raise SelectionError('Running managed host has no generation identity; cleanup refused')
        references.add(generation)
    return references


def plan(store, record, *, min_age_hours=24, now=None, process_ids=None):
    if not math.isfinite(min_age_hours) or min_age_hours < 0:
        raise SelectionError('Minimum generation age must be finite and nonnegative')
    if store.pending_transition():
        raise SelectionError('Unfinished transition; generation cleanup refused')
    state = store.state()
    retained = {value for value in [state['desired'], state['last_good'], state['previous_good']] if value}
    retained.update(store.images.referenced_generations())
    if record.get('generation_id'):
        retained.add(record['generation_id'])
    retained.update(process_references(store.generations, record) if process_ids is None else process_ids)
    retained.discard('image-base')
    checked = set()
    # A state-only generation can use a private worker owned by an older code
    # generation. Follow those bindings transitively; ancestry alone is not a
    # runtime dependency and must not retain every historical code snapshot.
    while retained - checked:
        identifier = next(iter(retained - checked))
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise SelectionError('Malformed retained generation identity; cleanup refused')
        directory = store.generations / identifier
        if directory.is_symlink() or directory.resolve() != directory or not directory.is_dir():
            raise SelectionError('Retained generation is missing or unsafe; cleanup refused')
        path = directory / 'generation.json'
        if path.exists():
            profile = json.loads(path.read_text())
            if profile.get('id') != identifier or not isinstance(profile.get('workers'), dict):
                raise SelectionError('Retained generation bindings are malformed; cleanup refused')
            for prefix in profile['workers'].values():
                if not isinstance(prefix, str) or not Path(prefix).is_absolute():
                    raise SelectionError('Malformed retained worker prefix; cleanup refused')
                worker = Path(prefix)
                if worker.is_relative_to(store.generations):
                    parts = worker.relative_to(store.generations).parts
                    if len(parts) != 3 or not ID.fullmatch(parts[0]) or not parts[1].startswith('environment-') or parts[2] != 'venv':
                        raise SelectionError('Unsafe retained worker prefix; cleanup refused')
                    retained.add(parts[0])
            for node in profile.get('nodes',{}).values():
                if 'source_archive' in node:
                    archive=Path(node['source_archive'])
                    if (archive.parent.parent!=store.generations or not ID.fullmatch(archive.parent.name)
                            or not archive.name.startswith('source-') or not archive.name.endswith('.tar.gz')):
                        raise SelectionError('Unsafe retained source archive; cleanup refused')
                    retained.add(archive.parent.name)
        # An orphan installer can still own an unfinished generation without a
        # generation.json. Retain its entire final prefix until the process ends.
        elif identifier not in (process_ids if process_ids is not None else set()):
            # Process-discovered incomplete candidates are also safe to retain.
            # State references, in contrast, must always have a valid profile.
            if identifier in {state['desired'], state['last_good'], state['previous_good'], record.get('generation_id')}:
                raise SelectionError('Retained state has no generation manifest; cleanup refused')
        checked.add(identifier)
    now = time.time() if now is None else now
    candidates, skipped = [], []
    for directory in sorted(store.generations.iterdir()):
        info = directory.lstat()
        if not ID.fullmatch(directory.name) or not stat.S_ISDIR(info.st_mode):
            skipped.append({'name': directory.name, 'reason': 'unmanaged-or-symlink'})
            continue
        if directory.name in retained:
            continue
        if now - info.st_mtime < min_age_hours * 3600:
            skipped.append({'name': directory.name, 'reason': 'minimum-age'})
            continue
        # lstat deliberately avoids following shared GPU payload symlinks.
        allocated, seen = 0, set()
        for path in directory.rglob('*'):
            item = path.lstat()
            key = (item.st_dev, item.st_ino)
            if stat.S_ISREG(item.st_mode) and key not in seen:
                allocated += item.st_blocks * 512
                seen.add(key)
        candidates.append({'id': directory.name, 'allocated_bytes': allocated})
    return {'retained': sorted(retained), 'candidates': candidates, 'skipped': skipped,
            'minimum_age_hours': min_age_hours, 'estimated_allocated_bytes': sum(item['allocated_bytes'] for item in candidates)}


def collect(store, record, *, apply=False, min_age_hours=24):
    result = plan(store, record, min_age_hours=min_age_hours)
    result.update(applied=apply, removed=[], scope='Managed generations only; storage and package caches are excluded')
    if not apply:
        return result
    if not shutil.rmtree.avoids_symlink_attacks:
        raise SelectionError('This platform lacks safe directory removal')
    journal = store.control / 'gc' / (uuid.uuid4().hex + '.json')
    durable_json(journal, dict(result, phase='removing'))
    for item in result['candidates']:
        directory = store.generations / item['id']
        if directory.is_symlink() or directory.resolve() != directory:
            raise SelectionError('Generation changed during cleanup')
        shutil.rmtree(directory)
        result['removed'].append(item['id'])
        durable_json(journal, dict(result, phase='removing'))
    durable_json(journal, dict(result, phase='complete'))
    result['journal'] = str(journal)
    return result
