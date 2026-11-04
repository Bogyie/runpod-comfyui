"""Load only the HTTP backend and reviewed host nodes, never the full catalog."""
import hashlib
import importlib
import importlib.machinery
import json
import sys
import types
from pathlib import Path


def namespace(name, path):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        module.__package__ = name
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
        sys.modules[name] = module
    return sys.modules[name]


def load_host():
    root = Path(__file__).resolve().parent
    name = '_comfyctl_itools_host_' + hashlib.sha256(str(root).encode()).hexdigest()[:12]
    namespace(name, root)
    # Bypass upstream nodes/__init__.py, which imports every compute node.
    namespace(name+'.nodes', root/'nodes')
    importlib.import_module(name+'.backend.iserver')
    importlib.import_module(name+'.backend.prompter_multi')
    shared = importlib.import_module(name+'.backend.shared')
    policy = json.loads((root/'_comfyctl_policy.json').read_text())
    mappings, display = {}, {}
    for node_id, definition in policy['host_nodes'].items():
        module = importlib.import_module(name+'.nodes.'+definition['module'])
        mappings[node_id] = getattr(module, definition['class'])
        label = definition['display_name']
        display[node_id] = label if shared.get_user_node_display_name_preferences() else 'iTools '+label
    return mappings, display
