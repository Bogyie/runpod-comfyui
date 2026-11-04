"""Synthetic media and observations for disposable VHS integration tests."""
import importlib
import json
import math
import os
import sys
import torch


class Media:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'count':('INT',)}}
    RETURN_TYPES=('IMAGE','MASK','LATENT','AUDIO')
    FUNCTION='run'
    def run(self,count):
        values=torch.arange(count,dtype=torch.float32)/10
        images=values[:,None,None,None].expand(count,32,64,3).contiguous()
        masks=values[:,None,None].expand(count,32,64).contiguous()
        latent={'samples':values[:,None,None,None].expand(count,4,4,8).contiguous(),
                'noise_mask':(values/10+0.1)[:,None,None,None].expand(count,1,4,8).contiguous(),'gate_marker':'retain'}
        t=torch.arange(16000,dtype=torch.float32)/16000
        audio={'waveform':(0.2*torch.sin(2*math.pi*440*t))[None,None,:],'sample_rate':16000}
        return images,masks,latent,audio


class Inspect:
    kind='IMAGE'
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'data':(cls.kind,),'indices':('STRING',)}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,data,indices):
        ids=[int(x) for x in indices.split(',')] if indices.strip() else []
        tensor=data['samples'] if self.kind=='LATENT' else data
        means=tensor.flatten(1).mean(dim=1)
        expected=torch.tensor(ids,dtype=torch.float32)/10
        if not torch.isfinite(tensor).all() or not torch.allclose(means,expected,atol=1e-6):raise RuntimeError('VHS tensor values/order changed')
        if self.kind=='LATENT':
            noise=data['noise_mask'].flatten(1).mean(dim=1)
            if data['gate_marker']!='retain' or not torch.allclose(noise,expected/10+0.1,atol=1e-6):raise RuntimeError('VHS latent metadata/noise mask changed')
        return {'ui':{'text':[json.dumps({'kind':self.kind,'shape':list(tensor.shape),'means':means.tolist()})]}}


class InspectMask(Inspect):kind='MASK'
class InspectLatent(Inspect):kind='LATENT'


class BatchAudit:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'manager':('VHS_BatchManager',),'files':('VHS_FILENAMES',)}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,manager,files):
        state={'host_pid':os.getpid(),'inputs':len(manager.inputs),'outputs':len(manager.outputs),
               'suspended_generators':sum(bool(getattr(item[0],'gi_suspended',False)) for item in manager.inputs.values())}
        return {'ui':{'text':[json.dumps(state)]}}


class State:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self):
        import nodes,latent_preview
        from server import PromptServer
        module=nodes.NODE_CLASS_MAPPINGS['VHS_VideoCombine'].__module__
        package=module.rsplit('.',1)[0]
        utils=importlib.import_module(package+'.utils')
        preview=importlib.import_module(package+'.latent_preview')
        data={'host_pid':os.getpid(),'class_modules':{n:nodes.NODE_CLASS_MAPPINGS[n].__module__ for n in ['VHS_VideoCombine','VHS_LoadVideoPath','VHS_BatchManager','VHS_SplitImages','VHS_SelectLatents']},
              'queue_is_host':utils.prompt_queue is PromptServer.instance.prompt_queue,
              'latent_hook_preserved':latent_preview.get_previewer is preview.get_latent_video_previewer,
              'ffmpeg_path':utils.ffmpeg_path,'worker_catalog_imported_on_host':'worker_nodes' in sys.modules}
        return {'ui':{'text':[json.dumps(data)]}}


OPEN_INPUT=None
OPEN_PATH=None


class CaptureInput:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'manager':('VHS_BatchManager',),'images':('IMAGE',),'video_path':('STRING',)}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,manager,images,video_path):
        global OPEN_INPUT,OPEN_PATH
        if not manager.inputs:raise RuntimeError('No active VHS input to inspect')
        OPEN_INPUT=next(iter(manager.inputs.values()))[0]
        OPEN_PATH=video_path
        if not OPEN_INPUT.gi_suspended:raise RuntimeError('VHS decoder is not suspended between batches')
        return {'ui':{'text':[json.dumps({'frames':len(images),'suspended':True})]}}


class AssertClosed:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'manager':('VHS_BatchManager',)}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='run'
    def run(self,manager):
        import psutil
        if OPEN_INPUT is None or OPEN_INPUT.gi_frame is not None or manager.inputs:raise RuntimeError('VHS reset did not close the held decoder generator')
        files=[f.path for f in psutil.Process().open_files() if f.path==OPEN_PATH]
        if files:raise RuntimeError('VHS reset left the video file descriptor open')
        return {'ui':{'text':[json.dumps({'held_generator_closed':True,'video_file_descriptors':0})]}}


NODE_CLASS_MAPPINGS={'ComfyctlVHSMedia':Media,'ComfyctlVHSInspectImages':Inspect,'ComfyctlVHSInspectMasks':InspectMask,'ComfyctlVHSInspectLatents':InspectLatent,'ComfyctlVHSBatchAudit':BatchAudit,'ComfyctlVHSHostState':State,'ComfyctlVHSCaptureInput':CaptureInput,'ComfyctlVHSAssertClosed':AssertClosed}
