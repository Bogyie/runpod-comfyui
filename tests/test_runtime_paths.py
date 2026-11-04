"""Exercise managed data mapping against the exact audited ComfyUI folder_paths."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT / '.work/upstreams/comfyui/2c75dc1b379a59e0880619d029607af5169a62ef'


@unittest.skipUnless((COMFY / 'folder_paths.py').is_file(), 'reproduce pinned ComfyUI snapshot first')
class RuntimePathsTests(unittest.TestCase):
    def run_case(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'user').mkdir()
            (root / 'models/checkpoints').mkdir(parents=True)
            (root / 'models/checkpoints/probe.safetensors').write_text('not-a-model')
            program = f'import sys;sys.path[:0]=[{str(ROOT / "runtime")!r},{str(COMFY)!r}]\n' + body
            result = subprocess.run([sys.executable, '-I', '-c', program], text=True, capture_output=True,
                                    env=dict(os.environ, COMFYCTL_STORAGE_DIR=str(root), COMFYCTL_COMFY_ROOT=str(COMFY)))
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_real_folder_paths_resolves_models_and_data_under_storage(self):
        result = self.run_case("""from runtime_paths import configure
configure()
import folder_paths as f,os,json
from pathlib import Path
root=Path(os.environ['COMFYCTL_STORAGE_DIR'])
print(json.dumps({'checkpoint':f.get_full_path('checkpoints','probe.safetensors')==str(root/'models/checkpoints/probe.safetensors'),
'user':f.get_user_directory()==str(root/'user'),'input':f.get_input_directory()==str(root/'input'),
'custom_nodes':f.get_folder_paths('custom_nodes')==[os.environ['COMFYCTL_COMFY_ROOT']+'/custom_nodes']}))
""")
        self.assertEqual(result, {'checkpoint': True, 'user': True, 'input': True, 'custom_nodes': True})

    def test_conflicting_path_flag_is_rejected_instead_of_silently_ignored(self):
        result = self.run_case("""from comfy.cli_args import args
args.models_directory='/unmanaged/models'
from runtime_paths import configure
import json
try:configure()
except RuntimeError as exc:print(json.dumps(str(exc)))
else:raise AssertionError('Conflicting path flag accepted')
""")
        self.assertIn('models_directory=', result)

    def test_unpropagated_extra_paths_are_rejected(self):
        result = self.run_case("""from comfy.cli_args import args
args.extra_model_paths_config=[['unmanaged.yaml']]
from runtime_paths import configure
import json
try:configure()
except RuntimeError as exc:print(json.dumps(str(exc)))
else:raise AssertionError('Unpropagated model path accepted')
""")
        self.assertIn('not yet propagated', result)


if __name__ == '__main__':
    unittest.main()
