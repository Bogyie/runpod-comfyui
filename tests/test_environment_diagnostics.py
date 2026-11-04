"""State provenance and marker-aware drift detection, without package mutation."""
import json
from pathlib import Path
import tempfile
import unittest

from comfyctl.environments import locked_versions, live_status, version_drift


class DiagnosticTests(unittest.TestCase):
    def test_lock_markers_do_not_report_windows_only_package_missing_on_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'tools.txt'
            lock.write_text("example_pkg==1.2 \\\n    --hash=sha256:unused\ncolorama==0.4.6 ; sys_platform == 'win32' \\\n    --hash=sha256:unused\n")
            self.assertEqual(locked_versions(lock, {'sys_platform': 'linux'}), {'example-pkg': '1.2'})

    def test_default_native_model_fixture_destinations_are_accepted(self):
        import yaml
        from comfyctl.models import safe_target
        fixture = Path(__file__).resolve().parents[1] / 'tests/fixtures/models-worker-smoke.yaml'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for model in yaml.safe_load(fixture.read_text())['models']:
                self.assertEqual(safe_target(root, model['target']), root.resolve() / model['target'])

    def test_missing_extra_and_changed_packages_remain_distinct(self):
        self.assertEqual(version_drift({'Example_Pkg': '2', 'extra': '1'}, {'example-pkg': '1', 'absent': '1'}),
                         {'missing': ['absent'], 'unexpected': ['extra'], 'changed': {'example-pkg': {'expected': '1', 'actual': '2'}}})

    def test_stale_or_foreign_ready_file_is_not_a_live_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / '1').mkdir()
            (proc / '1/status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
            (proc / '42').mkdir()
            (proc / '42/cmdline').write_bytes(b'python\x00/opt/runtime/control/run_comfy.py\x00')
            record = {'phase': 'ready', 'runtime_id': 'image', 'pid_namespace': 'current', 'child_pid': 42, 'updated_at': 100}
            self.assertTrue(live_status(record, 'image', now=110, namespace='current', proc=proc)['healthy'])
            self.assertIn('different-container', live_status(record, 'image', now=110, namespace='new-container', proc=proc)['issues'])
            self.assertIn('stale-or-future-heartbeat', live_status(record, 'image', now=200, namespace='current', proc=proc)['issues'])
            self.assertIn('runtime-identity-mismatch', live_status(record, 'new-image', now=110, namespace='current', proc=proc)['issues'])
            for stamp in ['invalid', float('nan')]:
                record['updated_at'] = stamp
                self.assertIn('invalid-heartbeat', live_status(record, 'image', now=110, namespace='current', proc=proc)['issues'])


if __name__ == '__main__':
    unittest.main()
