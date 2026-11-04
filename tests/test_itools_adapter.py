"""Adapter source guards must reject drift and output escapes before mutation."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT/'tools/rebuild/apply_itools_adapter.py'
spec = importlib.util.spec_from_file_location('itools_adapter',SCRIPT)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@unittest.skipUnless((ROOT/'.work/upstreams/itools/a8f2fef227ca5b0cb9321c39ac7b874a906b1a5b').is_dir(), "reproduce pinned source first")
class IToolsAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'ComfyUI-iTools'
        self.source = json.loads((ROOT/'locks/upstreams.lock.json').read_text())['sources']['itools']
        snapshot = ROOT/'.work/upstreams/itools'/self.source['commit']
        shutil.copytree(snapshot,self.root)
        self.assets = ROOT/'build/adapters/itools'

    def test_unknown_source_rejected_without_partial_patch(self):
        original = (self.root/'__init__.py').read_bytes()
        path = self.root/'nodes/prompt_saver.py'
        path.write_text(path.read_text()+'\n# drift\n')
        with self.assertRaisesRegex(ValueError,'unknown iTools source'):
            adapter.apply(self.root,self.source,self.assets)
        self.assertEqual((self.root/'__init__.py').read_bytes(),original)
        self.assertFalse((self.root/'_upstream_init.py').exists())

    def test_generated_file_escape_rejected_before_patch(self):
        external = Path(self.temp.name)/'external'
        external.write_text('untouched')
        (self.root/'_comfyctl_policy.json').symlink_to(external)
        original = (self.root/'__init__.py').read_bytes()
        with self.assertRaisesRegex(ValueError,'Unsafe adapter output'):
            adapter.apply(self.root,self.source,self.assets)
        self.assertEqual(external.read_text(),'untouched')
        self.assertEqual((self.root/'__init__.py').read_bytes(),original)
        self.assertFalse((self.root/'_upstream_init.py').exists())


if __name__ == '__main__':
    unittest.main()
