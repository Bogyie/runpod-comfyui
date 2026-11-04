"""Exercise the patched decision logic without importing untrusted node packages."""
import ast
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "tools/rebuild/apply_comfy_env_patch.py"
SPEC = importlib.util.spec_from_file_location("comfy_env_patch", SCRIPT)
guards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guards)


class GuardTests(unittest.TestCase):
    @unittest.skipUnless((SCRIPT.parents[2] / '.work/comfy-env-0.3.89/comfy_env/isolation/wrap.py').is_file(),
                         "reproduce pinned artifact first")
    def test_real_registration_refuses_missing_worker_before_host_import(self):
        original = SCRIPT.parents[2] / '.work/comfy-env-0.3.89/comfy_env/isolation/wrap.py'
        source = guards.transformed('isolation/wrap.py', original.read_bytes()).decode()
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_nodes')
        code = compile(ast.Module(body=[function], type_ignores=[]), 'patched-register-nodes', 'exec')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'custom_nodes/Example'
            (root / 'nodes').mkdir(parents=True)
            (root / 'nodes/comfy-env.toml').write_text('[dependencies]\n')
            inspector = types.SimpleNamespace(
                stack=lambda: [None, types.SimpleNamespace(filename=str(root / '__init__.py'), frame=None)],
                getmodule=lambda frame: types.SimpleNamespace(__name__='test_example'),
            )
            metadata = types.ModuleType('comfy_env.isolation.metadata')
            metadata.fetch_metadata = metadata.build_proxy_class = lambda **kw: None
            cache = types.ModuleType('comfy_env.environment.cache')
            cache.find_comfyui_source_dir = lambda path: root.parent.parent
            scope = {'__package__': 'comfy_env.isolation', 'Path': Path, 'os': os,
                     'inspect': inspector, '_log': lambda msg: None, '_cleanup_stale_workers': lambda: None,
                     '_find_env_dir': lambda *a, **kw: None}
            exec(code, scope)
            modules = {'comfy_env.isolation.metadata': metadata, 'comfy_env.environment.cache': cache}
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {'COMFYCTL_REQUIRE_ISOLATION': '1'}):
                with self.assertRaisesRegex(RuntimeError, 'Required isolation environment is missing'):
                    scope['register_nodes']()

    def test_explicit_target_does_not_require_driver_and_returns_exact_stack(self):
        # The actual generated guard block is tested; no replacement resolver is implemented here.
        source = "def resolve():\n    bootstrap_cuda = '12.8'\n    python_version = '3.11'\n    torch_version = '2.10.0'\n" + guards.CUDA_GUARD
        scope = {"os": os, "sys": types.SimpleNamespace(platform="linux"), "log": lambda msg: None}
        exec(compile(source, "cuda-guard", "exec"), scope)
        with patch.dict(os.environ, {"COMFYCTL_BUILD_CUDA": "12.8"}):
            result = scope["resolve"]()
        self.assertEqual(result, ("https://download.pytorch.org/whl/cu128", "12.8", "12", "3.11", "2.10.0"))
        with patch.dict(os.environ, {"COMFYCTL_BUILD_CUDA": "13.0"}), self.assertRaises(RuntimeError):
            scope["resolve"]()

    def test_unknown_upstream_is_never_patched(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            guards.transformed("install/workspace.py", b"unrecognized upstream")

    def test_validation_finishes_before_any_file_is_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "install").mkdir()
            target = root / "install/workspace.py"
            target.write_bytes(b"original")
            with self.assertRaises(ValueError):
                guards.apply(root)
            self.assertEqual(target.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
