"""Provenance, mapping and dependency boundaries before executing source."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from comfyctl.node_install import environment_name, extract_source, inspect_requirements, stage_node, restore_disabled
from comfyctl.node_sources import analyze, NodeSourceError


class NodeInstallPolicyTests(unittest.TestCase):
    def test_update_rejects_image_and_unknown_nodes_before_any_preparation(self):
        store=Mock()
        store.base={'nodes':{'base':{}}}
        store.desired.return_value={'nodes':{'base':{'repository':'owner/base'}}}
        for name in ['base','missing']:
            with self.subTest(name=name),self.assertRaisesRegex(NodeSourceError, 'previously added'):
                stage_node(store,SimpleNamespace(name=name,action='update'))
        store.fork_code.assert_not_called()

    def test_disabled_update_preserves_source_and_revalidates_final_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'custom_nodes/ComfyUI-example';directory.mkdir(parents=True)
            (directory/'__init__.py').write_text('new-code')
            receipt={'smoke_workflow':'passed'}
            profile={'comfy_root':str(root),'nodes':{'example':{'directory':'ComfyUI-example','enabled':True}},'validation':receipt}
            store=Mock();store.save_candidate.side_effect=lambda value:value
            final,smoke=restore_disabled(store,profile,'example')
            self.assertFalse(final['nodes']['example']['enabled'])
            self.assertIsNone(final['validation'])
            self.assertEqual(smoke,receipt)
            self.assertEqual((root/'custom_nodes/ComfyUI-example.disabled/__init__.py').read_text(),'new-code')

    def test_worker_names_match_pinned_sdk_convention(self):
        self.assertEqual(environment_name('ComfyUI-my-node', 'managed_worker/comfy-env.toml'), 'mynode-managedworker')
        self.assertEqual(environment_name('ComfyUI-Test', 'comfy-env.toml'), 'test')

    def test_archive_is_checked_before_extraction(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            item = tarfile.TarInfo('repo/__init__.py')
            source = b'raise RuntimeError("must not execute during extraction")'
            item.size = len(source)
            archive.addfile(item, io.BytesIO(source))
        data = buffer.getvalue()
        plan = analyze('o/r', 'a'*40, data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extract_source(data, root/'valid', plan['files'])
            self.assertEqual(hashlib.sha256((root/'valid/__init__.py').read_bytes()).hexdigest(), plan['files']['__init__.py'])
            with self.assertRaises(NodeSourceError):
                extract_source(data, root/'invalid', {})
            self.assertFalse((root/'invalid').exists())

    def test_dependency_mismatch_cuda_and_managed_variable_overrides(self):
        base = {'requirements': [], 'configuration': {}}
        inspect_requirements(base, {'numpy':'2.4.6'})
        for plan in [dict(base, requirements=[{'requirements':['numpy<2'], 'review_required_lines':[]}]),
                     dict(base, requirements=[{'requirements':[], 'review_required_lines':['-r hidden.txt']}]),
                     dict(base, configuration={'nodes/comfy-env.toml':{'cuda':{'packages':['flash-attn']}}}),
                     dict(base, configuration={'nodes/comfy-env.toml':{'dependencies':{'bpy':'*'}}}),
                     dict(base, configuration={'nodes/comfy-env.toml':{'env_vars':{'PYTHONPATH':'/opt/runtime/venv'}}})]:
            with self.subTest(plan=plan), self.assertRaises(NodeSourceError):
                inspect_requirements(plan, {'numpy':'2.4.6'})
        inspect_requirements(dict(base, requirements=[{'requirements':['numpy>=2; sys_platform=="linux"'], 'review_required_lines':[]}]), {'numpy':'2.4.6'})


if __name__ == '__main__':
    unittest.main()
