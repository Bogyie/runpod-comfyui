"""Preserve KJ host hooks/models and delegate reviewed tensor operations."""
import json
from pathlib import Path
from comfy_env import register_nodes

_policy=json.loads((Path(__file__).parent/'policy.json').read_text())
_isolated,_display=register_nodes(nodes_package='worker_nodes')
if set(_isolated)!=set(_policy['worker_nodes']):
    raise RuntimeError('KJNodes isolated registration does not match reviewed policy')
# Validate required isolation before running any upstream host startup hooks.
from ._upstream_init import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, WEB_DIRECTORY
for _name,_definition in _policy['worker_nodes'].items():
    if _name not in NODE_CLASS_MAPPINGS or NODE_CLASS_MAPPINGS[_name].__name__!=_definition['class']:
        raise RuntimeError('KJNodes upstream catalog changed: '+_name)
NODE_CLASS_MAPPINGS=dict(NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_isolated)
