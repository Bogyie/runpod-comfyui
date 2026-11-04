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



class WorkerPrefixTests(unittest.TestCase):
    def patched_function(self, name):
        original = SCRIPT.parents[2] / '.work/comfy-env-0.3.89/comfy_env/environment/cache.py'
        if not original.is_file():
            self.skipTest('reproduce pinned artifact first')
        tree = ast.parse(guards.transformed('environment/cache.py', original.read_bytes()))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        scope = {'Path':Path,'os':os,'get_workspace_dir':lambda _:Path('/legacy/workspace')}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'patched-worker-prefix','exec'),scope)
        return scope[name]

    def test_generations_use_different_final_worker_prefixes(self):
        resolve = self.patched_function('get_workspace_env_dir')
        with patch.dict(os.environ,{'COMFYCTL_WORKER_ROOT':'/workspace/generations/a/workers'}):
            first = resolve(None,'sam3-nodes')
        with patch.dict(os.environ,{'COMFYCTL_WORKER_ROOT':'/workspace/generations/b/workers'}):
            second = resolve(None,'sam3-nodes')
        self.assertNotEqual(first,second)
        self.assertEqual(first,Path('/workspace/generations/a/workers/sam3-nodes'))

    def test_invalid_worker_paths_fail_before_process_creation(self):
        resolve = self.patched_function('get_workspace_env_dir')
        for root,name in [('relative/path','sam3-nodes'),('/workspace/.pixi-cache','sam3-nodes'),
                          ('/workers','../host'),('/workers','..'),('/workers','bad.pixi')]:
            with self.subTest(root=root,name=name), patch.dict(os.environ,{'COMFYCTL_WORKER_ROOT':root}):
                with self.assertRaises(RuntimeError):resolve(None,name)

    def test_generation_map_uses_exact_prefix_without_virtualenv_aliases(self):
        resolve = self.patched_function('get_workspace_env_dir')
        with tempfile.TemporaryDirectory() as tmp:
            mapping = Path(tmp) / 'workers.json'
            mapping.write_text('{"sam3-nodes":"/opt/workers/sam3-nodes"}')
            with patch.dict(os.environ, {'COMFYCTL_WORKER_MAP_FILE': str(mapping), 'COMFYCTL_WORKER_ROOT': '/wrong/root'}):
                self.assertEqual(resolve(None, 'sam3-nodes'), Path('/opt/workers/sam3-nodes'))
                with self.assertRaisesRegex(RuntimeError, 'absent'):
                    resolve(None, 'unreviewed-worker')

    def test_unconfigured_prefix_preserves_upstream_pixi_layout(self):
        resolve = self.patched_function('get_workspace_env_dir')
        with patch.dict(os.environ,{'COMFYCTL_WORKER_ROOT':''}):
            self.assertEqual(resolve(None,'sam3-nodes'),Path('/legacy/workspace/.pixi/envs/sam3-nodes'))



class ManagedSubprocessTests(unittest.TestCase):
    def build_environment(self, variables):
        original = SCRIPT.parents[2] / '.work/comfy-env-0.3.89/comfy_env/isolation/wrap.py'
        if not original.is_file():
            self.skipTest('reproduce pinned artifact first')
        tree = ast.parse(guards.transformed('isolation/wrap.py', original.read_bytes()))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build_isolation_env')
        scope = {'Path': Path, 'os': os, 'sys': types.SimpleNamespace(platform='linux'),
                 '_build_isolation_env_linux': lambda env, python: env}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'managed-worker-env', 'exec'), scope)
        with patch.dict(os.environ, variables, clear=True):
            return scope['build_isolation_env'](Path('/private/worker/bin/python'))

    def test_managed_workers_ignore_inherited_python_path_injection(self):
        result = self.build_environment({'COMFYCTL_REQUIRE_ISOLATION': '1', 'PYTHONPATH': '/host/site-packages',
                                         'PYTHONHOME': '/other/python', 'PYTHONSTARTUP': '/unexpected.py',
                                         'PYTHONUSERBASE': '/mutable/user'})
        self.assertEqual(result['PYTHONNOUSERSITE'], '1')
        for name in ['PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE']:
            self.assertNotIn(name, result)

    def test_unmanaged_upstream_behavior_is_retained(self):
        self.assertEqual(self.build_environment({'PYTHONPATH': '/explicit/upstream/path'})['PYTHONPATH'], '/explicit/upstream/path')


class AttentionPolicyTests(unittest.TestCase):
    def test_explicit_backend_disables_unrequested_auto_extensions(self):
        for mode in ['pytorch','xformers']:
            args=types.SimpleNamespace(use_pytorch_cross_attention=False,disable_xformers=False,
                                       use_sage_attention=True,use_flash_attention=True)
            module=types.ModuleType('comfy.cli_args');module.args=args
            with patch.dict(sys.modules,{'comfy.cli_args':module}), patch.dict(os.environ,{'COMFYCTL_WORKER_ATTENTION':mode}):
                exec(compile(guards.ATTENTION_POLICY,'attention-policy','exec'),{'os':os})
            self.assertEqual(args.use_pytorch_cross_attention,mode=='pytorch')
            self.assertEqual(args.disable_xformers,mode=='pytorch')
            self.assertFalse(args.use_sage_attention)
            self.assertFalse(args.use_flash_attention)

    def test_unknown_backend_is_rejected(self):
        with patch.dict(os.environ,{'COMFYCTL_WORKER_ATTENTION':'unknown'}):
            with self.assertRaisesRegex(RuntimeError,'Unsupported worker attention'):
                exec(compile(guards.ATTENTION_POLICY,'attention-policy','exec'),{'os':os})


if __name__ == "__main__":
    unittest.main()
