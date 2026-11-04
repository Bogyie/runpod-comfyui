"""VHS queue and startup hooks must stay on host; worker metadata needs no queue."""
import ast
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('vhs_adapter',ROOT/'tools/rebuild/apply_vhs_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)


class VHSAdapterTests(unittest.TestCase):
    def test_missing_worker_prevents_host_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['__init__.py','policy.json']:shutil.copyfile(ROOT/'build/adapters/vhs'/name,root/name)
            marker=root/'host_started'
            (root/'_upstream_init.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("started")\n')
            def reject(**kwargs):raise RuntimeError('Required isolation environment is missing')
            comfy=types.ModuleType('comfy_env');comfy.register_nodes=reject
            spec=importlib.util.spec_from_file_location('_test_vhs_required',root/'__init__.py',submodule_search_locations=[str(root)])
            module=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,{'comfy_env':comfy,'_test_vhs_required':module}):
                with self.assertRaisesRegex(RuntimeError,'Required isolation'):spec.loader.exec_module(module)
            self.assertFalse(marker.exists())

    @unittest.skipUnless((ROOT/'.work/upstreams/video-helper-suite/4d907bee61e92c2e65af3bd6383a4e4d356126d1').is_dir(),'reproduce pinned source first')
    def test_actual_patch_keeps_host_queue_and_avoids_worker_server_instance(self):
        source=json.loads((ROOT/'locks/upstreams.lock.json').read_text())['sources']['video-helper-suite']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'VHS';shutil.copytree(ROOT/'.work/upstreams/video-helper-suite'/source['commit'],root)
            adapter.apply(root,source,ROOT/'build/adapters/vhs')
            tree=ast.parse((root/'videohelpersuite/utils.py').read_text())
            statement=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prompt_queue' for t in n.targets))
            code=compile(ast.Module(body=[statement],type_ignores=[]),'patched-vhs-queue','exec')
            scope={'os':os,'server':types.SimpleNamespace(PromptServer=object())}
            with patch.dict(os.environ,{'COMFYCTL_VHS_WORKER':'1'}):exec(code,scope)
            self.assertIsNone(scope['prompt_queue'])
            queue=object();scope['server']=types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(prompt_queue=queue)))
            with patch.dict(os.environ,{'COMFYCTL_VHS_WORKER':'0'}):exec(code,scope)
            self.assertIs(scope['prompt_queue'],queue)


    @unittest.skipUnless((ROOT/'.work/upstreams/video-helper-suite/4d907bee61e92c2e65af3bd6383a4e4d356126d1').is_dir(),'reproduce pinned source first')
    def test_reset_explicitly_closes_first_slot_input_generator(self):
        source=json.loads((ROOT/'locks/upstreams.lock.json').read_text())['sources']['video-helper-suite']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'VHS';shutil.copytree(ROOT/'.work/upstreams/video-helper-suite'/source['commit'],root)
            adapter.apply(root,source,ROOT/'build/adapters/vhs')
            tree=ast.parse((root/'videohelpersuite/nodes.py').read_text())
            cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BatchManager')
            scope={};exec(compile(ast.Module(body=[cls],type_ignores=[]),'patched-vhs-manager','exec'),scope)
            closed=[]
            def stream():
                try:
                    while True:
                        value=yield 'frame'
                        if value is not None:return
                finally:closed.append(True)
            gen=stream();self.addCleanup(gen.close);next(gen)
            manager=scope['BatchManager'](2)
            manager.inputs['video']=(gen,64,32,False)
            manager.reset()
            self.assertTrue(closed)
            self.assertIsNone(gen.gi_frame)
            self.assertEqual(manager.inputs,{})


if __name__=='__main__':unittest.main()
