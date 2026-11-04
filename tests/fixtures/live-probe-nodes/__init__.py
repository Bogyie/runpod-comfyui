"""A real queued task, bind-mounted only in disposable transition test containers."""
import json
from pathlib import Path
import time


class Delay:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'token': ('STRING', {}), 'seconds': ('FLOAT', {'default': 1, 'min': 0, 'max': 30})}}
    RETURN_TYPES = ()
    FUNCTION = 'run'
    OUTPUT_NODE = True
    CATEGORY = 'test-only'

    def run(self, token, seconds):
        if not token.isalnum():
            raise ValueError('Test token must be alphanumeric')
        path = Path('/workspace/state/live-jobs')
        path.mkdir(exist_ok=True)
        started = time.time()
        (path / (token + '.json')).write_text(json.dumps({'started': started, 'finished': None}))
        time.sleep(seconds)
        (path / (token + '.json')).write_text(json.dumps({'started': started, 'finished': time.time()}))
        return {'ui': {'text': [token]}}


NODE_CLASS_MAPPINGS = {'ComfyctlLiveDelay': Delay}
