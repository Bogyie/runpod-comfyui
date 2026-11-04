"""Image changes preserve compatible selections and isolate incompatible histories."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime'))
from selection import Store, SelectionError, durable_json
from comfyctl.generation_gc import plan


class ImageStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        source = self.root/'image/ComfyUI'
        (source/'custom_nodes/Example').mkdir(parents=True)
        (source/'main.py').write_text('# frozen core\n')
        (source/'custom_nodes/Example/__init__.py').write_text('NODE_CLASS_MAPPINGS={}\n')
        self.base = {'runtime_id':'a'*64, 'compatibility_id':'c'*64,
                     'abi_id':'d'*64, 'environment_id':'e'*64, 'application_id':'f'*64,
                     'comfy_root':str(source), 'host_python':'/opt/runtime/venv/bin/python',
                     'workers':{'example':'/opt/workers/example'},
                     'nodes':{'example':{'directory':'Example','enabled':True}}}
        self.a = self.store('a')
        with self.a.locked():
            self.a.prepare_image()
            self.a.write_state(self.a.state())

    def store(self, runtime, compatibility='c'):
        baseline = self.root/('baseline-'+runtime+'.json')
        durable_json(baseline, dict(self.base, runtime_id=runtime*64,
                                   compatibility_id=compatibility*64))
        return Store(self.root/'control',self.root/'generations',baseline)

    def candidate(self, store, enabled):
        profile, changed = store.stage_node_state('example',enabled)
        self.assertTrue(changed)
        store.validated(profile, {'kind':'unit-protocol-test'})
        store.select(profile['id'])
        return profile

    def test_cli_change_adopts_existing_generation_and_allows_bidirectional_rollback(self):
        with self.a.locked():
            old = self.candidate(self.a,False)
        files = dict(old['files'])
        b = self.store('b')
        with b.locked():
            b.prepare_image()
            self.assertEqual(b.state()['runtime_id'],'b'*64)
            self.assertEqual(b.desired()['id'],old['id'])
            self.assertEqual(b.desired()['files'],files)
            new = self.candidate(b,True)
            self.assertEqual(new['runtime_id'],'b'*64)
        with self.a.locked():
            self.a.prepare_image()
            self.assertEqual(self.a.desired()['id'],new['id'])
            self.assertEqual(self.a.desired()['workers'],old['workers'])
            self.a.select(old['id'])
        with b.locked():
            b.prepare_image()
            self.assertFalse(b.desired()['nodes']['example']['enabled'])

    def test_foreign_image_needs_explicit_reset_and_return_restores_old_selection(self):
        with self.a.locked():
            old = self.candidate(self.a,False)
        foreign = self.store('b','9')
        with foreign.locked():
            foreign.prepare_image()
            with self.assertRaisesRegex(SelectionError,'another image'):
                foreign.state()
            self.assertEqual(json.loads(foreign.state_file.read_text())['desired'],old['id'])
            foreign.reset()
            self.assertEqual(foreign.desired()['id'],'image-base')
        with self.a.locked():
            self.a.prepare_image()
            self.assertEqual(self.a.desired()['id'],old['id'])

    def test_inactive_history_and_source_archive_owners_are_gc_roots(self):
        with self.a.locked():
            owner = self.candidate(self.a,False)
            child = self.candidate(self.a,True)
            path = self.a.generations/child['id']/'generation.json'
            manifest = json.loads(path.read_text())
            manifest['nodes']['example']['source_archive'] = str(self.a.generations/owner['id']/'source-example.tar.gz')
            durable_json(path,manifest)
        foreign = self.store('b','9')
        with foreign.locked():
            foreign.prepare_image()
            foreign.reset()
            result = plan(foreign,{},min_age_hours=0,process_ids=set())
        self.assertIn(child['id'],result['retained'])
        self.assertIn(owner['id'],result['retained'])
        self.assertFalse(result['candidates'])

    def test_foreign_transition_blocks_switch_but_compatible_transition_recovers(self):
        with self.a.locked():
            candidate,_ = self.a.stage_node_state('example',False)
            self.a.validated(candidate,{'kind':'unit-protocol-test'})
            with patch('selection.os.readlink',return_value='test'):
                self.a.begin_live(candidate['id'],'image-base')
            self.a.select(candidate['id'])
        foreign = self.store('b','9')
        with foreign.locked(), self.assertRaisesRegex(SelectionError,'previous image first'):
            foreign.prepare_image()
        b = self.store('b')
        with b.locked():
            b.prepare_image()
            b.recover_interrupted()
            self.assertEqual(b.state()['runtime_id'],'b'*64)
            self.assertEqual(b.state()['desired'],'image-base')

    def test_corrupt_history_refuses_restore_and_cleanup(self):
        snapshot = self.a.images.directory('c'*64)/'selection.json'
        snapshot.write_text('{broken')
        with self.assertRaisesRegex(SelectionError,'Malformed image selection'):
            self.a.images.referenced_generations()
        durable_json(snapshot,dict(self.a.state(),compatibility_id='9'*64))
        with self.assertRaisesRegex(SelectionError,'cleanup refused'):
            self.a.images.referenced_generations()

    def test_malformed_history_and_incomplete_selection_fail_with_recovery_error(self):
        durable_json(self.a.images.root/'history.json',{'current':['invalid']})
        with self.a.locked(), self.assertRaisesRegex(SelectionError,'Malformed image history'):
            self.a.prepare_image()
        snapshot=self.a.images.directory('c'*64)/'selection.json'
        durable_json(snapshot,{'runtime_id':'a'*64,'revision':0,'desired':'image-base'})
        with self.assertRaisesRegex(SelectionError,'Malformed image selection'):
            self.a.images.referenced_generations()

    def test_reused_compatibility_id_cannot_hide_environment_change(self):
        b = self.store('b')
        b.base['environment_id']='1'*64
        with b.locked(), self.assertRaisesRegex(SelectionError,'different baseline'):
            b.prepare_image()
