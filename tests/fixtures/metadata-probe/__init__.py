"""Test-only real SDK registration against an existing private worker prefix."""
from pathlib import Path
from comfy_env.isolation.metadata import fetch_metadata, build_proxy_class

root=Path(__file__).parent
env=Path('/opt/workers/depthanythingv3-nodes')
data=fetch_metadata(env,root,'metadata_nodes',root,{})
NODE_CLASS_MAPPINGS={name:build_proxy_class(name,meta,env,root,[str(root)],None,{}) for name,meta in data['nodes'].items()}
