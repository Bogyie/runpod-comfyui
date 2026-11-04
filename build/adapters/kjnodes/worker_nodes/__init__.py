"""Physical namespace retained for metadata and persistent-worker imports."""
import importlib
import json
import os
import sys
from pathlib import Path

if os.environ.get('COMFYCTL_KJNODES_WORKER')!='1':
    raise RuntimeError('KJNodes compute catalog may only load in its worker')
_root=Path(__file__).resolve().parent.parent
__path__.append(str(_root))
sys.path.insert(0,os.environ['COMFYUI_BASE'])
import folder_paths
folder_paths.add_model_folder_path('kjnodes_fonts',str(_root/'fonts'))
_policy=json.loads((_root/'policy.json').read_text())
NODE_CLASS_MAPPINGS={}
NODE_DISPLAY_NAME_MAPPINGS={}
for _name,_definition in _policy['worker_nodes'].items():
    _module=importlib.import_module('.'+_definition['module'],__name__)
    _cls=getattr(_module,_definition['class'])
    # Fail metadata scanning rather than advertising an empty/broken schema.
    _inputs=_cls.INPUT_TYPES()
    if any(type(_value) is not dict for _value in _inputs.values()):
        raise RuntimeError('Unreviewed dynamic input dictionary: '+_name)
    NODE_CLASS_MAPPINGS[_name]=_cls
    NODE_DISPLAY_NAME_MAPPINGS[_name]=_definition['display_name']
