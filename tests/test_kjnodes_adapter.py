"""KJ adapter drift and missing isolation must fail before host startup hooks."""
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
SCRIPT=ROOT/'tools/rebuild/apply_kjnodes_adapter.py'
spec=importlib.util.spec_from_file_location('kj_adapter',SCRIPT)
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)


class KJAdapterTests(unittest.TestCase):
    def test_required_worker_failure_does_not_import_upstream_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['__init__.py','policy.json']:
                shutil.copyfile(ROOT/'build/adapters/kjnodes'/name,root/name)
            marker=root/'host_hook_ran'
            (root/'_upstream_init.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("ran")\n')
            def reject(**kwargs):raise RuntimeError('Required isolation environment is missing')
            comfy_env=types.ModuleType('comfy_env');comfy_env.register_nodes=reject
            spec=importlib.util.spec_from_file_location('_test_kj_required',root/'__init__.py',submodule_search_locations=[str(root)])
            module=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,{'comfy_env':comfy_env,'_test_kj_required':module}):
                with self.assertRaisesRegex(RuntimeError,'Required isolation'):
                    spec.loader.exec_module(module)
            self.assertFalse(marker.exists())

    @unittest.skipUnless((ROOT/'.work/upstreams/kjnodes/ab72eda7ffad6280422d71ab7d54d3fb87c0ba18').is_dir(),'reproduce pinned source first')
    def test_unknown_node_source_rejected_before_root_change(self):
        source=json.loads((ROOT/'locks/upstreams.lock.json').read_text())['sources']['kjnodes']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'KJNodes'
            shutil.copytree(ROOT/'.work/upstreams/kjnodes'/source['commit'],root)
            original=(root/'__init__.py').read_bytes()
            path=root/'nodes/image_nodes.py';path.write_text(path.read_text()+'\n# drift\n')
            with self.assertRaisesRegex(ValueError,'unknown KJNodes source'):
                adapter.apply(root,source,ROOT/'build/adapters/kjnodes')
            self.assertEqual((root/'__init__.py').read_bytes(),original)
            self.assertFalse((root/'_upstream_init.py').exists())


if __name__=='__main__':unittest.main()
