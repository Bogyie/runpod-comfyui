"""Test-only KJ data contracts and host observations; never shipped in images."""
import importlib.util
import json
import os
import sys
import torch


class Bbox:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'malformed':('BOOLEAN',),'offset':('INT',)}}
    RETURN_TYPES=('BBOX',)
    FUNCTION='run'
    def run(self,malformed,offset):return ([1,2] if malformed else [(12+offset,8,24,16)],)


class InspectInts:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{name:('INT',) for name in ['x','y','width','height','cx','cy']}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,**kwargs):return {'ui':{'text':[json.dumps(kwargs)]}}


class InspectMask:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'mask':('MASK',),'width':('INT',),'height':('INT',),'count':('INT',)}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,mask,width,height,count):
        if not torch.isfinite(mask).all() or not torch.allclose(mask,torch.full_like(mask,0.5)):
            raise RuntimeError('KJ mask values changed')
        return {'ui':{'text':[json.dumps({'shape':list(mask.shape),'width':width,'height':height,'count':count,'mean':mask.mean().item()})]}}


class State:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self):
        import nodes
        result={'host_pid':os.getpid(),'worker_catalog_imported_on_host':'worker_nodes' in sys.modules,
                'class_modules':{n:nodes.NODE_CLASS_MAPPINGS[n].__module__ for n in ['ColorMatchV2','ResizeMask','BboxToInt','FastPreview','ModelPassThrough']},
                'host_has_color_matcher':importlib.util.find_spec('color_matcher') is not None,
                'host_imported_color_matcher':'color_matcher' in sys.modules}
        return {'ui':{'text':[json.dumps(result)]}}


class SigmaFloats:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{}}
    RETURN_TYPES=('FLOAT',)
    FUNCTION='run'
    def run(self):return ([1.0,0.5,0.0],)


class InspectSigmas:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'sigmas':('SIGMAS',)}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,sigmas):
        value=sigmas.cpu().tolist()
        if value!=[1.0,0.5,0.0]:raise RuntimeError('KJ sigma values changed')
        return {'ui':{'text':[json.dumps(value)]}}


NODE_CLASS_MAPPINGS={'ComfyctlKJBbox':Bbox,'ComfyctlKJInspectInts':InspectInts,'ComfyctlKJInspectMask':InspectMask,'ComfyctlKJHostState':State,'ComfyctlKJSigmaFloats':SigmaFloats,'ComfyctlKJInspectSigmas':InspectSigmas}
