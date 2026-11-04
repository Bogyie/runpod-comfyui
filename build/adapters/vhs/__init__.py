"""Keep VHS streaming/queue state on host; isolate stateless tensor batching."""
import json
from pathlib import Path
from comfy_env import register_nodes

_policy=json.loads((Path(__file__).parent/'policy.json').read_text())
_isolated,_display=register_nodes(nodes_package='worker_nodes')
if set(_isolated)!=set(_policy['worker_nodes']):
    raise RuntimeError('VHS required worker registration is incomplete')
from ._upstream_init import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, WEB_DIRECTORY
NODE_CLASS_MAPPINGS=dict(NODE_CLASS_MAPPINGS)
for _name,_proxy in _isolated.items():
    _original=NODE_CLASS_MAPPINGS[_name]
    if _original.__name__!=_policy['worker_nodes'][_name]['class']:
        raise RuntimeError('VHS upstream catalog changed: '+_name)
    # Preserve the host's type/UI helpers and rich upstream documentation.
    _proxy.INPUT_TYPES=_original.INPUT_TYPES
    for _attribute in ['DESCRIPTION','CATEGORY','RETURN_NAMES','OUTPUT_TOOLTIPS','INPUT_IS_LIST','OUTPUT_IS_LIST','DEPRECATED','EXPERIMENTAL']:
        if hasattr(_original,_attribute):setattr(_proxy,_attribute,getattr(_original,_attribute))
    for _attribute in ['IS_CHANGED','VALIDATE_INPUTS']:
        if _attribute in _original.__dict__:setattr(_proxy,_attribute,getattr(_original,_attribute))
    NODE_CLASS_MAPPINGS[_name]=_proxy
