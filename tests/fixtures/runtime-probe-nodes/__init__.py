"""Observability only; bind-mounted into disposable runtime gate containers."""
import json
import os
from pathlib import Path


def paths():
    import folder_paths as f
    model = Path(f.get_folder_paths('checkpoints')[0]) / 'runtime-marker.safetensors'
    return {'uid': os.getuid(), 'pid': os.getpid(), 'base': f.base_path, 'models': f.models_dir,
            'input': f.get_input_directory(), 'output': f.get_output_directory(), 'user': f.get_user_directory(),
            'temp': f.get_temp_directory(), 'custom_nodes': f.get_folder_paths('custom_nodes'),
            'checkpoint_paths': f.get_folder_paths('checkpoints'),
            'marker': model.read_text(), 'input_files': sorted(os.listdir(f.get_input_directory()))}


class RuntimeProbe:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {}}
    RETURN_TYPES = ('STRING',)
    FUNCTION = 'run'
    CATEGORY = 'test-only'

    def run(self):
        from comfy_env.isolation.workers.subprocess import SubprocessWorker
        worker = SubprocessWorker(python=Path('/opt/workers/depthanythingv3-nodes/bin/python'),
                                  working_dir=Path(__file__).parent,
                                  sys_path=['/opt/probe/ComfyUI', str(Path(__file__).parent)],
                                  env=dict(os.environ, COMFY_CPU='1'), name='runtime-path-gate', health_check_timeout=30)
        try:
            remote = worker.call_method(module_name='runtime_paths_case', class_name='Paths', method_name='run', kwargs={})
        finally:
            worker.shutdown()
        return (json.dumps({'host': paths(), 'worker': remote, 'worker_stopped': not worker.is_alive()}),)


NODE_CLASS_MAPPINGS = {'ComfyctlRuntimeProbe': RuntimeProbe}
