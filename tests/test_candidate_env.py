"""Reject unsafe resolver inputs before a candidate prefix can be modified."""
from pathlib import Path
import unittest

from comfyctl.candidate_env import CandidateEnvironmentError, frozen_pins, verify_gpu_pins

ROOT = Path(__file__).resolve().parents[1]
HASH = 'a' * 64


class CandidateLockTests(unittest.TestCase):
    def test_existing_complete_locks_keep_exact_gpu_artifacts(self):
        gpu = frozen_pins((ROOT / 'locks/gpu/linux-amd64-cu128.txt').read_bytes())
        for path in [ROOT / 'locks/host/linux-amd64-cu128.txt', *sorted((ROOT / 'locks/workers').glob('*.txt'))]:
            with self.subTest(path=path):
                pins = frozen_pins(path.read_bytes())
                verify_gpu_pins(pins, gpu)
                self.assertEqual(pins['comfy-env'], '0.3.89')

    def test_rejects_resolver_directives_source_builds_and_unhashed_inputs(self):
        invalid = ['', 'foo==1', 'foo>=1 --hash=sha256:' + HASH,
                   '--index-url https://evil.example/simple', '-r other.txt',
                   'foo @ https://example.com/foo.whl --hash=sha256:' + HASH,
                   'foo==1; python_version>"3" --hash=sha256:' + HASH,
                   'foo==1 --hash=sha256:' + HASH + ' \\',
                   'foo==1 --hash=sha256:' + HASH + '\nfoo==1 --hash=sha256:' + HASH]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(CandidateEnvironmentError):
                frozen_pins(value.encode())

    def test_gpu_changes_missing_packages_and_additions_are_rejected(self):
        baseline = {'torch': '2.10.0+cu128', 'xformers': '0.0.35', 'nvidia-cudnn-cu12': '9.10.2.21'}
        for value in [dict(baseline, torch='2.9.0'), {'torch': baseline['torch']}, dict(baseline, **{'nvidia-new-cu12': '1'})]:
            with self.subTest(value=value), self.assertRaises(CandidateEnvironmentError):
                verify_gpu_pins(value, baseline)
        verify_gpu_pins(dict(baseline, pillow='12.0'), baseline)


if __name__ == '__main__':
    unittest.main()
