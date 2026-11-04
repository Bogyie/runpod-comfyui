"""Import upstream compute modules under a real, worker-importable namespace."""
import json
import os
import sys
from pathlib import Path

if os.environ.get('COMFYCTL_ITOOLS_WORKER') != '1':
    raise RuntimeError('iTools worker catalog may only load inside its isolated environment')
_root = Path(__file__).resolve().parent.parent
__path__.append(str(_root))
# ComfyUI owns the top-level nodes module; the plugin also has a nodes directory.
sys.path.insert(0, os.environ['COMFYUI_BASE'])
from .iTools_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
_policy = json.loads((_root/'_comfyctl_policy.json').read_text())
NODE_CLASS_MAPPINGS = {k:v for k,v in NODE_CLASS_MAPPINGS.items() if k not in _policy['host_nodes']}
NODE_DISPLAY_NAME_MAPPINGS = {k:v for k,v in NODE_DISPLAY_NAME_MAPPINGS.items() if k in NODE_CLASS_MAPPINGS}
