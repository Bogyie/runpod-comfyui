"""Test-only observations and synthetic host VAE dispatch, never shipped."""
import json
import os
import sys
import torch


class State:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{}}
    RETURN_TYPES=()
    FUNCTION='run'
    OUTPUT_NODE=True
    def run(self):
        import nodes
        names=['iToolsTextReplacer','iToolsPreviewImage','iToolsKSampler','iToolsVaePreview']
        state={'host_pid':os.getpid(),'class_modules':{n:nodes.NODE_CLASS_MAPPINGS[n].__module__ for n in names},
               'host_compute_imports':sorted(n for n in sys.modules if n.startswith('_comfyctl_itools_host_') and '.nodes.' in n),
               'worker_catalog_imported_on_host':'worker_nodes' in sys.modules}
        return {'ui':{'text':[json.dumps(state)]}}


class HostVAE:
    def __init__(self):self.owner=os.getpid()
    def decode(self,samples):
        if os.getpid()!=self.owner:raise RuntimeError('Synthetic host VAE crossed process boundary')
        return samples[:,:3].permute(0,2,3,1)


class SyntheticVAEInput:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{}}
    RETURN_TYPES=('LATENT','VAE')
    FUNCTION='run'
    def run(self):return {'samples':torch.full((1,4,8,8),0.5)},HostVAE()


NODE_CLASS_MAPPINGS={'ComfyctlIToolsHostState':State,'ComfyctlIToolsSyntheticVAE':SyntheticVAEInput}
