"""Only stateless image/mask/latent operators cross this process boundary."""
import importlib
import json
import os
import sys
from pathlib import Path

if os.environ.get('COMFYCTL_VHS_WORKER')!='1':
    raise RuntimeError('VHS compute catalog must load in its worker')
_root=Path(__file__).resolve().parent.parent
__path__.append(str(_root))
sys.path.insert(0,os.environ['COMFYUI_BASE'])
_policy=json.loads((_root/'policy.json').read_text())
_module=importlib.import_module('.videohelpersuite.image_latent_nodes',__name__)
NODE_CLASS_MAPPINGS={name:getattr(_module,item['class']) for name,item in _policy['worker_nodes'].items()}
NODE_DISPLAY_NAME_MAPPINGS={name:item['display_name'] for name,item in _policy['worker_nodes'].items()}
