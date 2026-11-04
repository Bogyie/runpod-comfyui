"""Root-owned selection snapshots for execution-compatible image groups."""
import json
from pathlib import Path
import re

from selection import SelectionError, durable_json

IDENTITY = re.compile(r'[0-9a-f]{64}')
GENERATION = re.compile(r'(?:image-base|[0-9a-f]{32})')


def compatibility(base):
    return base.get('compatibility_id', base['runtime_id'])


class ImageHistory:
    def __init__(self, control, baseline):
        self.control = Path(control)
        self.base = baseline
        self.root = self.control/'images'
        self.key = compatibility(baseline)
        self.enabled = 'compatibility_id' in baseline

    def directory(self, key):
        if not isinstance(key,str) or not IDENTITY.fullmatch(key):
            raise SelectionError('Invalid image compatibility identity')
        path = self.root/key
        if self.root.is_symlink() or path.is_symlink() or path.resolve()!=path:
            raise SelectionError('Unsafe image history directory')
        return path

    def register(self):
        if not self.enabled:return
        path = self.directory(self.key)/'baseline.json'
        if path.exists():
            try:
                previous = json.loads(path.read_text())
                if not isinstance(previous,dict):raise ValueError('Expected baseline object')
            except ValueError as error:
                raise SelectionError('Malformed image baseline; use explicit recovery') from error
            old = {key:value for key,value in previous.items() if key!='runtime_id'}
            current = {key:value for key,value in self.base.items() if key!='runtime_id'}
            if old != current:
                raise SelectionError('Compatibility identity was reused for a different baseline')
        durable_json(path,self.base)

    @staticmethod
    def load_selection(path):
        try:
            state=json.loads(path.read_text())
            if (not isinstance(state,dict) or not all(key in state for key in
                    ['runtime_id','revision','desired','last_good','previous_good']) or
                    not isinstance(state['runtime_id'],str) or
                    not isinstance(state['revision'],int) or state['revision']<0 or
                    not all(isinstance(state.get(key),str) and GENERATION.fullmatch(state[key])
                            for key in ['desired']) or
                    any(state.get(key) is not None and (not isinstance(state[key],str) or not GENERATION.fullmatch(state[key]))
                        for key in ['last_good','previous_good'])):
                raise ValueError('Malformed selection')
            return state
        except (ValueError,KeyError,TypeError) as error:
            raise SelectionError('Malformed image selection; use explicit recovery') from error

    def save(self, state):
        if not self.enabled:return
        key = state.get('compatibility_id')
        if not key:
            # An older preview is preserved for inspection, never adopted by
            # guessing which source/ABI it used.
            return
        durable_json(self.directory(key)/'selection.json',state)

    def prepare(self, state_file):
        if not self.enabled:return
        self.register()
        history_file = self.root/'history.json'
        try:
            history = json.loads(history_file.read_text()) if history_file.exists() else {}
            if (not isinstance(history,dict) or any(value is not None and
                    (not isinstance(value,str) or not IDENTITY.fullmatch(value))
                    for value in history.values())):
                raise ValueError('Invalid history identity')
        except ValueError as error:
            raise SelectionError('Malformed image history; use explicit recovery') from error
        if history.get('current') != self.key:
            history = {'current':self.key,'previous':history.get('current')}
            durable_json(history_file,history)
        if not state_file.exists():return
        state = self.load_selection(state_file)
        previous_key = state.get('compatibility_id')
        self.save(state)
        if previous_key == self.key:
            if state['runtime_id'] != self.base['runtime_id']:
                state.update(runtime_id=self.base['runtime_id'],revision=state['revision']+1)
                durable_json(state_file,state)
            self.save(state)
            return
        target = self.directory(self.key)/'selection.json'
        if target.exists():
            restored = self.load_selection(target)
            if restored.get('compatibility_id') != self.key:
                raise SelectionError('Image history selection identity drift')
            restored.update(runtime_id=self.base['runtime_id'],revision=max(state['revision'],restored['revision'])+1)
            durable_json(state_file,restored)
            self.save(restored)
        # With no matching snapshot, leave the foreign selection untouched.
        # Supervisor enters recovery mode; only an explicit reset/rebase may
        # replace it. There is no silent image-base fallback.

    def selections(self):
        if not self.enabled or not self.root.exists():return
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir():continue
            path=self.directory(directory.name)/'selection.json'
            if not path.exists():continue
            state=self.load_selection(path)
            if state.get('compatibility_id')!=directory.name:
                raise SelectionError('Malformed image history selection; cleanup refused')
            yield state

    def referenced_generations(self):
        result=set()
        for state in self.selections():
            result.update(value for value in [state.get('desired'),state.get('last_good'),state.get('previous_good')] if value)
        return result
