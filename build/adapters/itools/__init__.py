"""iTools host HTTP routes and explicit model-object exceptions."""
import json
from pathlib import Path
from comfy_env import register_nodes
from ._comfyctl_adapter import load_host

NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = register_nodes(nodes_package='worker_nodes')
_policy = json.loads((Path(__file__).parent / '_comfyctl_policy.json').read_text())
_expected = set(_policy['base_node_ids']) - set(_policy['host_nodes'])
if not _expected.issubset(NODE_CLASS_MAPPINGS):
    raise RuntimeError('iTools isolated registration is incomplete: ' + str(sorted(_expected-set(NODE_CLASS_MAPPINGS))))
_host, _display = load_host()
NODE_CLASS_MAPPINGS.update(_host)
NODE_DISPLAY_NAME_MAPPINGS.update(_display)
WEB_DIRECTORY = './web'
