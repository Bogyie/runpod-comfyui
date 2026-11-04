"""Cleanup preserves live, recovery and transitive private-prefix references."""
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime'))
from selection import Store, SelectionError, durable_json
from comfyctl.generation_gc import plan, collect, process_references


class GenerationGCTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        baseline = self.root/'baseline.json'
        durable_json(baseline, {'runtime_id':'runtime'})
        self.store = Store(self.root/'control', self.root/'generations', baseline)
        self.store.control.mkdir();self.store.generations.mkdir()

    def generation(self, digit, dependencies=()):
        identifier = digit*32
        directory = self.store.generations/identifier
        directory.mkdir()
        (directory/'data').write_text('private-environment')
        durable_json(directory/'generation.json', {'id':identifier, 'workers':{
            str(index):str(self.store.generations/(dependency*32)/'environment-node/venv')
            for index,dependency in enumerate(dependencies)}})
        os.utime(directory, (100,100))
        return identifier

    def state(self, desired, last_good=None, previous_good=None):
        durable_json(self.store.state_file, {'runtime_id':'runtime','desired':desired,
            'last_good':last_good,'previous_good':previous_good,'revision':1})

    def test_transitive_bindings_live_and_recovery_are_retained_not_all_ancestors(self):
        owner = self.generation('a', ['b']);second=self.generation('b')
        desired = self.generation('c', ['a']);previous=self.generation('d')
        active = self.generation('e');unused=self.generation('f')
        self.state(desired, desired, previous)
        result=plan(self.store, {'generation_id':active}, now=100000, process_ids=set())
        self.assertEqual(set(result['retained']), {owner,second,desired,previous,active})
        self.assertEqual([item['id'] for item in result['candidates']], [unused])

    def test_plan_apply_and_interrupted_partial_generation_do_not_touch_storage(self):
        self.state('image-base')
        old=self.generation('a')
        failed=self.store.generations/('b'*32);failed.mkdir();(failed/'unfinished').write_text('partial')
        outside=self.root/'storage';outside.mkdir();(outside/'model').write_text('keep')
        (self.store.generations/('c'*32)).symlink_to(outside, target_is_directory=True)
        with patch('comfyctl.generation_gc.process_references', return_value=set()):
            self.assertFalse(collect(self.store, {}, min_age_hours=0)['applied'])
            self.assertTrue((self.store.generations/old).exists())
            result=collect(self.store, {}, apply=True, min_age_hours=0)
        self.assertEqual(set(result['removed']), {old,'b'*32})
        self.assertEqual((outside/'model').read_text(), 'keep')
        self.assertEqual(json.loads(Path(result['journal']).read_text())['phase'], 'complete')

    def test_missing_retained_dependency_and_transition_refuse_all_cleanup(self):
        desired=self.generation('a', ['b']);unused=self.generation('c');self.state(desired)
        with self.assertRaisesRegex(SelectionError, 'missing or unsafe'):
            plan(self.store, {}, process_ids=set())
        self.assertTrue((self.store.generations/unused).exists())
        durable_json(self.store.control/'transition.json', {'phase':'draining'})
        with self.assertRaisesRegex(SelectionError, 'Unfinished transition'):
            plan(self.store, {}, process_ids=set())

    def test_age_and_orphan_process_are_protected(self):
        self.state('image-base');old=self.generation('a');young=self.generation('b')
        os.utime(self.store.generations/young, (99999,99999))
        result=plan(self.store, {}, now=100000, process_ids={old})
        self.assertFalse(result['candidates'])
        self.assertIn(old, result['retained'])
        for age in [-1,float('nan'),float('inf')]:
            with self.assertRaises(SelectionError):plan(self.store, {}, min_age_hours=age, process_ids=set())

    def test_process_prefix_and_unknown_host_detection(self):
        proc=self.root/'proc';proc.mkdir();entry=proc/'123';entry.mkdir()
        (entry/'cmdline').write_bytes(str(self.store.generations/('a'*32)/'environment-x/request.json').encode()+b'\x00')
        self.assertEqual(process_references(self.store.generations, {}, proc), {'a'*32})
        (entry/'cmdline').write_bytes(b'python\x00/opt/runtime/control/run_comfy.py\x00')
        (entry/'environ').write_bytes(b'COMFYCTL_GENERATION_ID='+b'b'*32+b'\x00')
        self.assertEqual(process_references(self.store.generations, {}, proc), {'b'*32})
        (entry/'environ').write_bytes(b'')
        with self.assertRaisesRegex(SelectionError, 'no generation identity'):
            process_references(self.store.generations, {}, proc)

    def test_interrupted_removal_records_progress_and_next_run_finishes(self):
        self.state('image-base');first=self.generation('a');second=self.generation('b')
        remove=shutil.rmtree
        def interrupted(path):
            if Path(path).name==second:
                raise OSError('injected interruption')
            remove(path)
        interrupted.avoids_symlink_attacks=True
        with patch('comfyctl.generation_gc.process_references', return_value=set()):
            with patch('comfyctl.generation_gc.shutil.rmtree', interrupted),self.assertRaises(OSError):
                collect(self.store, {}, apply=True, min_age_hours=0)
            journal=json.loads(next((self.store.control/'gc').iterdir()).read_text())
            self.assertEqual(journal['removed'],[first])
            self.assertEqual(journal['phase'],'removing')
            result=collect(self.store, {}, apply=True, min_age_hours=0)
        self.assertEqual(result['removed'],[second])


if __name__=='__main__':unittest.main()
