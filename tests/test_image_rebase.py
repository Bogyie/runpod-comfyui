"""Rebase selection is transactional and preserves old image recovery state."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from selection import Store, SelectionError, durable_json
from comfyctl.image_rebase import rebase, reusable_environment, satisfies


class ImageRebaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.stores=[]
        for digit,group,body in [('a','c','# old core\n'),('b','9','# upgraded core\n')]:
            source=self.root/digit/'ComfyUI'
            (source/'custom_nodes/Example').mkdir(parents=True)
            (source/'main.py').write_text(body)
            (source/'custom_nodes/Example/__init__.py').write_text('NODE_CLASS_MAPPINGS={}\n')
            baseline={'runtime_id':digit*64,'compatibility_id':group*64,'generation_schema':2,
                'abi_id':'d'*64,'environment_id':'e'*64,'application_id':digit*64,
                'comfy_root':str(source),'host_python':'/opt/runtime/venv/bin/python',
                'workers':{'example':'/opt/workers/example'},
                'nodes':{'example':{'directory':'Example','enabled':True}}}
            path=self.root/(digit+'.json');durable_json(path,baseline)
            self.stores.append(Store(self.root/'control',self.root/'generations',path))
        self.old,self.new=self.stores
        with self.old.locked():
            self.old.prepare_image()
            candidate,_=self.old.stage_node_state('example',False)
            self.old.validated(candidate,{'kind':'unit-protocol-test'})
            self.old.select(candidate['id'])
            self.old_id=candidate['id']
        with self.new.locked():self.new.prepare_image()

    @staticmethod
    def validate(store,profile,workflow=None):
        return store.validated(profile,{'kind':'unit-protocol-test','workflows':workflow})

    def test_new_core_preserves_node_state_and_image_rollback_restores_old_core(self):
        with self.new.locked(),patch('comfyctl.generations.validate',side_effect=self.validate):
            result=rebase(self.new,'c'*64)
            profile=self.new.desired()
            self.assertEqual((Path(profile['comfy_root'])/'main.py').read_text(),'# upgraded core\n')
            self.assertFalse(profile['nodes']['example']['enabled'])
            self.assertTrue(result['restart_required'])
            self.assertFalse(result['applied_to_running_process'])
            self.assertEqual(profile['validation']['rebase']['source_generation'],self.old_id)
        with self.old.locked():
            self.old.prepare_image()
            self.assertEqual(self.old.desired()['id'],self.old_id)
            self.assertEqual((Path(self.old.desired()['comfy_root'])/'main.py').read_text(),'# old core\n')

    def test_candidate_failure_leaves_foreign_selection_and_history_unchanged(self):
        before=self.new.state_file.read_bytes()
        history=self.old.images.directory('c'*64)/'selection.json'
        snapshot=history.read_bytes()
        with self.new.locked(),patch('comfyctl.generations.validate',side_effect=SelectionError('failed smoke')):
            with self.assertRaisesRegex(SelectionError,'failed smoke'):rebase(self.new,'c'*64)
        self.assertEqual(self.new.state_file.read_bytes(),before)
        self.assertEqual(history.read_bytes(),snapshot)

    def test_unknown_image_and_same_contract_refuse_rebase(self):
        with self.new.locked():
            for key,message in [('9'*64,'already compatible'),('1'*64,'baseline is missing')]:
                with self.assertRaisesRegex(SelectionError,message):rebase(self.new,key)

    def test_pin_satisfaction_honors_linux_markers_and_rejects_urls_and_missing_packages(self):
        pins={'numpy':'2.2.6'}
        self.assertTrue(satisfies(['numpy>=2','missing; sys_platform == "win32"'],pins))
        for requirements in [['numpy<2'],['missing'],['numpy @ https://example.org/package.whl']]:
            self.assertFalse(satisfies(requirements,pins))

    def test_frontend_update_preserves_other_frozen_packages(self):
        from probe_image_rebase import replace_requirement
        old='numpy==2.2.6 \\\n    --hash=sha256:aaa\ncomfyui-frontend-package==1.0 \\\n    --hash=sha256:bbb \\\n    --hash=sha256:ccc\nuv==0.10.8\n'
        replacement='comfyui-frontend-package==2.0 \\\n    --hash=sha256:ddd\n'
        updated=replace_requirement(old,'comfyui-frontend-package',replacement)
        self.assertEqual(updated,'numpy==2.2.6 \\\n    --hash=sha256:aaa\n'+replacement+'uv==0.10.8\n')
        with self.assertRaisesRegex(ValueError,'Missing'):
            replace_requirement(old,'missing',replacement)

    def test_prefix_reuse_requires_same_abi_and_current_core_requirements(self):
        current=SimpleNamespace(base={'abi_id':'same','comfy_root':'/current','worker_ui_packages_omitted':[]})
        source=SimpleNamespace(base={'abi_id':'same'})
        node={'environment_keys':['added'],'source_plan':{}}
        profile={'workers':{'added':'/workspace/runtime/generations/'+'a'*32+'/environment-added/venv'},
                 'environment_bindings':{'added':{'lock_sha256':'hash','receipt_sha256':'receipt'}}}
        pins={'numpy':'2.2.6','comfy-env':'0.3.89','uv':'0.10.8','comfy-kitchen':'1.0','comfy-aimdo':'1.0'}
        with patch('pathlib.Path.read_bytes',return_value=b'lock'),patch('pathlib.Path.read_text',return_value='numpy>=2'),\
                patch('comfyctl.image_rebase.frozen_pins',return_value=pins),\
                patch('comfyctl.image_rebase.verify_gpu_pins'),\
                patch('comfyctl.node_install.declared_requirements',return_value=[]):
            self.assertEqual(reusable_environment(current,source,profile,node)['prefix'],profile['workers']['added'])
            with patch('pathlib.Path.read_text',return_value='numpy>=3'):
                self.assertIsNone(reusable_environment(current,source,profile,node))
            source.base['abi_id']='different'
            self.assertIsNone(reusable_environment(current,source,profile,node))
