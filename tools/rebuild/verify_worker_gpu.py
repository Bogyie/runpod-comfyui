#!/usr/bin/env python3
"""Verify bidirectional CUDA tensor values through actual comfy-env workers.

Run inside the candidate container on a real GPU. This gate is independent of
model inference; it never treats a CPU fallback as a passing GPU worker result.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sys
import tempfile
from pathlib import Path

CASE = '''import os,sys,torch
import torch.nn.functional as F
class GpuCase:
    def run(self,image,q,k,v):
        if not all(t.is_cuda for t in (image,q,k,v)):
            raise RuntimeError("CUDA input tensors reached the worker on CPU")
        from comfy.cli_args import args
        from comfy.ldm.modules.attention import optimized_attention
        return {"image":image*2+1,"attention":F.scaled_dot_product_attention(q,k,v),
                "pid":os.getpid(),"prefix":sys.prefix,"torch":torch.__version__,
                "cuda":torch.version.cuda,"compute_capability":list(torch.cuda.get_device_capability()),
                "pytorch_policy":args.use_pytorch_cross_attention,"attention_function":getattr(optimized_attention,"__name__",type(optimized_attention).__name__)}
'''


def probe(root: Path, comfy: Path, expected_cc: str, expected_cuda: str) -> dict:
    import torch
    import torch.nn.functional as F
    if not torch.cuda.is_available():
        raise RuntimeError('GPU worker gate requires a CUDA GPU; CPU fallback cannot pass')
    cc='.'.join(map(str,torch.cuda.get_device_capability()))
    if cc!=expected_cc or torch.version.cuda!=expected_cuda:
        raise RuntimeError(f'Unexpected GPU stack: CC={cc}, CUDA={torch.version.cuda}')
    if os.environ.get('COMFY_CPU')=='1':
        raise RuntimeError('GPU worker gate cannot run with COMFY_CPU=1')
    sys.path.insert(0,str(comfy))
    from comfy.cli_args import args
    if args.cpu:raise RuntimeError('GPU worker gate cannot run with --cpu')
    args.use_pytorch_cross_attention=True
    from comfy_env.isolation.workers.subprocess import SubprocessWorker
    results={}
    with tempfile.TemporaryDirectory(prefix='comfyctl_gpu_bridge_') as tmp:
        case_dir=Path(tmp)
        (case_dir/'worker_gpu_case.py').write_text(CASE)
        for name in ['sam3-nodes','depthanythingv3-nodes']:
            prefix=root/name
            worker=SubprocessWorker(python=prefix/'bin/python',working_dir=comfy,sys_path=[tmp],
                                    env={'COMFYCTL_WORKER_ATTENTION':'pytorch'},name='gpu-gate-'+name,health_check_timeout=30)
            before=torch.cuda.memory_allocated()
            try:
                torch.manual_seed(12345)
                image=torch.arange(192,device='cuda',dtype=torch.float32).reshape(1,8,8,3)
                q,k,v=[torch.randn((1,4,32,64),device='cuda',dtype=torch.bfloat16) for _ in range(3)]
                reference=F.scaled_dot_product_attention(q.cpu().float(),k.cpu().float(),v.cpu().float())
                returned=worker.call_method(module_name='worker_gpu_case',class_name='GpuCase',method_name='run',
                                            kwargs={'image':image,'q':q,'k':k,'v':v})
                if returned['pid']==os.getpid() or Path(returned['prefix'])!=prefix:
                    raise RuntimeError('Node execution did not occur in the expected worker process/venv')
                if returned['cuda']!=expected_cuda or '.'.join(map(str,returned['compute_capability']))!=expected_cc:
                    raise RuntimeError('Worker used a different CUDA stack or GPU')
                if returned['pytorch_policy'] is not True or 'pytorch' not in returned['attention_function']:
                    raise RuntimeError(f'Worker attention policy did not select PyTorch: {returned["attention_function"]}')
                if not returned['image'].is_cuda or not returned['attention'].is_cuda:
                    raise RuntimeError('Worker CUDA tensors returned on CPU')
                if not torch.equal(returned['image'].cpu(),image.cpu()*2+1):
                    raise RuntimeError('CUDA tensor values changed across worker IPC')
                if not torch.isfinite(returned['attention']).all() or not torch.allclose(returned['attention'].cpu().float(),reference,atol=0.03,rtol=0.03):
                    raise RuntimeError('Worker BF16 attention disagrees with CPU reference')
                worker_pid=returned['pid']
                data={key:value for key,value in returned.items() if key not in {'image','attention'}}
                data.update({'cuda_tensor_roundtrip':'passed','bf16_sdpa_vs_cpu':'passed','host_pid':os.getpid()})
                del returned,image,q,k,v,reference
                gc.collect();torch.cuda.synchronize();torch.cuda.empty_cache()
            finally:
                worker.shutdown()
            if worker.is_alive():raise RuntimeError('Worker remained alive after shutdown')
            data.update({'shutdown':'passed','host_allocated_before_bytes':before,
                         'host_allocated_after_shutdown_bytes':torch.cuda.memory_allocated()})
            results[name]=data
    return {'kind':'native-worker-cuda-bridge-gate','gpu':torch.cuda.get_device_name(),
            'compute_capability':cc,'cuda':torch.version.cuda,'workers':results,
            'scope':'CUDA tensor values/device, BF16 SDPA, worker backend and shutdown only; not model inference or a zero-copy/total-VRAM guarantee'}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-root',type=Path,default=Path(os.environ.get('COMFYCTL_WORKER_ROOT','/opt/workers')))
    parser.add_argument('--comfy-root',type=Path,default=Path('/opt/probe/ComfyUI'))
    parser.add_argument('--expected-cc',required=True,choices=['9.0','12.0'])
    parser.add_argument('--expected-cuda',required=True)
    parser.add_argument('--image-digest',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',args.image_digest):
        parser.error('Image digest must be immutable sha256')
    args.output.unlink(missing_ok=True)
    value=probe(args.worker_root,args.comfy_root,args.expected_cc,args.expected_cuda)
    value['image_digest']=args.image_digest
    args.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=args.output.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');tmp.replace(args.output)
    print(json.dumps(value,sort_keys=True),flush=True)


if __name__=='__main__':
    main()
