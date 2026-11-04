"""Exercise code/environment/node snapshot selection and preserved-good recovery."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from selection import Store, SelectionError, durable_json


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        source = self.root / 'image/ComfyUI'
        (source / 'custom_nodes/Example').mkdir(parents=True)
        (source / 'custom_nodes/Example/__init__.py').write_text('NODE_CLASS_MAPPINGS = {}\n')
        (source / 'main.py').write_text('# frozen core\n')
        baseline = self.root / 'baseline.json'
        durable_json(baseline, {'runtime_id': 'a' * 64, 'comfy_root': str(source), 'host_python': '/opt/runtime/venv/bin/python',
                               'workers': {'example': '/opt/workers/example'},
                               'nodes': {'example': {'directory': 'Example', 'enabled': True, 'commit': 'frozen-source',
                                                     'required_nodes': ['Example'], 'lock_sha256': 'frozen-lock'}}})
        self.store = Store(self.root / 'control', self.root / 'generations', baseline)
        with self.store.locked():
            self.store.acknowledge({'phase': 'ready', 'runtime_id': 'a' * 64, 'generation_id': 'image-base',
                                    'pid_namespace': 'test', 'updated_at': 100}, 'test', now=110)

    def stage(self):
        profile, changed = self.store.stage_node_state('example', False)
        self.assertTrue(changed)
        return profile

    def test_unvalidated_snapshot_cannot_be_selected_and_preserves_data(self):
        model = self.root / 'storage/model.safetensors'
        model.parent.mkdir()
        model.write_text('user-data')
        with self.store.locked():
            profile = self.stage()
            self.assertTrue((Path(profile['comfy_root']) / 'custom_nodes/Example.disabled/__init__.py').is_file())
            self.assertEqual(profile['host_python'], '/opt/runtime/venv/bin/python')
            self.assertEqual(profile['workers'], {'example': '/opt/workers/example'})
            with self.assertRaisesRegex(SelectionError, 'not passed validation'):
                self.store.select(profile['id'])
            self.assertEqual(self.store.state()['desired'], 'image-base')
        self.assertEqual(model.read_text(), 'user-data')

    def test_deferred_selection_is_idempotent_and_rollback_uses_last_good(self):
        with self.store.locked():
            profile = self.store.validated(self.stage(), {'kind': 'unit-protocol-test'})
            self.store.select(profile['id'])
            same, changed = self.store.stage_node_state('Example', False)
            self.assertFalse(changed)
            self.assertEqual(same['id'], profile['id'])
            self.assertEqual(self.store.state()['last_good'], 'image-base')
            self.store.rollback()
            self.assertEqual(self.store.state()['desired'], 'image-base')

    def test_boot_acknowledgement_preserves_previous_good(self):
        with self.store.locked():
            profile = self.store.validated(self.stage(), {'kind': 'unit-protocol-test'})
            self.store.select(profile['id'])
            self.store.acknowledge({'phase': 'ready', 'runtime_id': 'a' * 64, 'generation_id': profile['id'],
                                    'pid_namespace': 'test', 'updated_at': 110}, 'test', now=115)
            self.assertEqual(self.store.state()['previous_good'], 'image-base')
            self.store.rollback()
            self.assertEqual(self.store.state()['desired'], 'image-base')

    def test_corrupt_selected_code_fails_closed_and_can_rollback_without_loading_it(self):
        with self.store.locked():
            profile = self.store.validated(self.stage(), {'kind': 'unit-protocol-test'})
            self.store.select(profile['id'])
            (Path(profile['comfy_root']) / 'main.py').write_text('corruption')
            with self.assertRaisesRegex(SelectionError, 'code drift'):
                self.store.desired()
            self.store.rollback()
            self.assertEqual(self.store.desired()['id'], 'image-base')

    def test_reset_preserves_corrupt_state_for_inspection(self):
        with self.store.locked():
            self.store.state_file.write_text('{interrupted-or-corrupt-json')
            self.store.reset()
            self.assertEqual(self.store.state()['desired'], 'image-base')
            archives = list(self.store.control.glob('previous-selection-*.json'))
            self.assertEqual(len(archives), 1)
            self.assertEqual(json.loads(archives[0].read_text())['preserved_raw_state'], '{interrupted-or-corrupt-json')

    def test_rollback_skips_a_corrupted_last_good_snapshot(self):
        with self.store.locked():
            profile = self.store.validated(self.stage(), {'kind': 'unit-protocol-test'})
            self.store.select(profile['id'])
            self.store.acknowledge({'phase': 'ready', 'runtime_id': 'a' * 64, 'generation_id': profile['id'],
                                    'pid_namespace': 'test', 'updated_at': 110}, 'test', now=115)
            pending, _ = self.store.stage_node_state('example', True)
            pending = self.store.validated(pending, {'kind': 'unit-protocol-test'})
            self.store.select(pending['id'])
            (Path(profile['comfy_root']) / 'main.py').write_text('corrupted-last-good')
            self.store.rollback()
            self.assertEqual(self.store.state()['desired'], 'image-base')

    def test_interrupted_live_transition_recovers_old_selection_and_unblocks_admission(self):
        with self.store.locked():
            profile = self.store.validated(self.stage(), {'kind': 'unit-protocol-test'})
            with patch('selection.os.readlink', return_value='test-namespace'):
                transaction = self.store.begin_live(profile['id'], 'image-base')
            self.store.select(profile['id'])
            self.store.transition_phase(transaction, 'switched')
            self.assertTrue((self.store.control / 'maintenance.json').exists())
            self.store.recover_interrupted()
            self.assertEqual(self.store.state()['desired'], 'image-base')
            self.assertEqual(self.store.transition()['phase'], 'recovered-on-boot')
            self.assertFalse((self.store.control / 'maintenance.json').exists())

    def test_committed_live_transition_is_not_rolled_back_on_boot(self):
        with self.store.locked():
            profile = self.store.validated(self.stage(), {'kind': 'unit-protocol-test'})
            with patch('selection.os.readlink', return_value='test-namespace'):
                transaction = self.store.begin_live(profile['id'], 'image-base')
            self.store.select(profile['id'])
            self.store.finish_live(transaction, 'committed')
            self.store.recover_interrupted()
            self.assertEqual(self.store.state()['desired'], profile['id'])

    def test_other_image_requires_explicit_reset(self):
        with self.store.locked():
            state = self.store.state()
            state['runtime_id'] = 'b' * 64
            durable_json(self.store.state_file, state)
            with self.assertRaisesRegex(SelectionError, 'another image'):
                self.store.state()
            self.store.reset()
            self.assertEqual(self.store.state()['runtime_id'], 'a' * 64)


if __name__ == '__main__':
    unittest.main()
