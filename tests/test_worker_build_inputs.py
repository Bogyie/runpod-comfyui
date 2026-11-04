"""Regress app-only updates accidentally invalidating all worker package layers."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/rebuild'))
from build_probe import prepare_worker_install_inputs


def hashes(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


class WorkerBuildInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = Path(self.temp.name)
        shutil.copytree(ROOT / 'locks/workers', self.context / 'worker-locks')
        self.definitions = json.loads((self.context / 'worker-locks/manifest.json').read_text())
        prepare_worker_install_inputs(self.context, self.definitions)

    def test_source_adapter_changes_update_runtime_identity_without_reinstalling_packages(self):
        before = hashes(self.context / 'worker-install')
        identities = hashes(self.context / 'worker-identities')
        updated = copy.deepcopy(self.definitions)
        updated['workers']['kjnodes']['commit'] = 'new-validated-source'
        updated['workers']['kjnodes']['adapter_files_sha256'] = {'new-adapter': 'new-hash'}
        prepare_worker_install_inputs(self.context, updated)
        self.assertEqual(before, hashes(self.context / 'worker-install'))
        self.assertNotEqual(identities, hashes(self.context / 'worker-identities'))
        self.assertEqual(json.loads((self.context / 'worker-identities/kjnodes-workernodes/worker-lock.json').read_text()), updated['workers']['kjnodes'])

    def test_one_dependency_lock_change_only_invalidates_its_worker(self):
        before = hashes(self.context / 'worker-install')
        updated = copy.deepcopy(self.definitions)
        worker = updated['workers']['itools']
        lock = self.context / 'worker-locks' / worker['lock_file']
        lock.write_text(lock.read_text() + '\n# revised frozen package input\n')
        worker['lock_sha256'] = hashlib.sha256(lock.read_bytes()).hexdigest()
        prepare_worker_install_inputs(self.context, updated)
        after = hashes(self.context / 'worker-install')
        changed = {name for name in before if before[name] != after[name]}
        self.assertEqual(changed, {'itools/manifest.json', 'itools/' + worker['lock_file']})

    def test_unrepresented_worker_cannot_silently_disappear_from_final_image(self):
        del self.definitions['workers']['itools']
        with self.assertRaisesRegex(ValueError, 'explicit Docker stages'):
            prepare_worker_install_inputs(self.context, self.definitions)


if __name__ == '__main__':
    unittest.main()
