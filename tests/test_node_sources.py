"""Source provenance and untrusted archive boundaries before any node execution."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from comfyctl.cli import main
from comfyctl.node_sources import analyze, archive_files, NodeSourceError, plan_source, source_identity

SHA = 'a' * 40


def archive(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for path, value in entries:
            member = tarfile.TarInfo(path)
            if isinstance(value, bytes):
                member.size = len(value)
                tar.addfile(member, io.BytesIO(value))
            else:
                member.type, member.linkname = value
                tar.addfile(member)
    return stream.getvalue()


class SourceInspectionTests(unittest.TestCase):
    def test_native_classification_does_not_execute_source_or_hooks(self):
        data = archive([('repo/__init__.py', b'raise RuntimeError("must never import")\nregister_nodes()\n'),
                        ('repo/install.py', b'raise RuntimeError("must never execute")'),
                        ('repo/nodes/comfy-env.toml', b'[pypi-dependencies]\npillow="*"\n[cuda]\npackages=["flash-attn"]'),
                        ('repo/requirements.txt', b'torch>=2\npillow==12.0\n-r more.txt\ncustom @ https://example.com/file.whl'),
                        ('repo/assets/test.bin', b'\x00\xff')])
        plan = analyze('owner/repo', SHA, data)
        self.assertEqual(plan['classification'], 'native-comfy-env-candidate')
        self.assertEqual(plan['hooks'], ['install.py'])
        self.assertEqual(plan['requirements'][0]['gpu_requirements'], ['torch>=2'])
        self.assertEqual(len(plan['requirements'][0]['review_required_lines']), 2)
        self.assertEqual(plan['files']['assets/test.bin'], hashlib.sha256(b'\x00\xff').hexdigest())
        self.assertFalse(plan['installation_ready'])
        self.assertEqual(plan, analyze('https://github.com/owner/repo.git', SHA, data))

    def test_config_alone_does_not_claim_isolation(self):
        data = archive([('repo/__init__.py', b''), ('repo/comfy-env.toml', b'[dependencies]\n')])
        self.assertEqual(analyze('o/r', SHA, data)['classification'], 'adapter-review-required')

    def test_rejects_unsafe_archives(self):
        bad = [('repo/../../escape.py', b'x'), ('/root/absolute.py', b'x'),
               ('repo/symlink', (tarfile.SYMTYPE, '/etc/passwd')),
               ('repo/hardlink', (tarfile.LNKTYPE, 'repo/__init__.py')),
               ('other/file.py', b'x'), ('repo/__init__.py', b'duplicate'),
               ('repo/back\\slash.py', b'x')]
        for item in bad:
            with self.subTest(item=item[0]), self.assertRaises(NodeSourceError):
                archive_files(archive([('repo/__init__.py', b''), item]))

    def test_member_expanded_and_compressed_limits(self):
        data = archive([('repo/__init__.py', b'12345')])
        for setting, limit in [('MEMBER_LIMIT', 0), ('EXPANDED_LIMIT', 4), ('FILE_LIMIT', 4), ('ARCHIVE_LIMIT', 1), ('TAR_LIMIT', 1)]:
            with self.subTest(setting=setting), patch('comfyctl.node_sources.' + setting, limit), self.assertRaises(NodeSourceError):
                archive_files(data)

    def test_provenance_rejected_before_network(self):
        for repository, commit in [('https://evil.test/o/r', SHA), ('o/r?token=secret', SHA), ('o/r', 'main'), ('o/r', 'A'*40)]:
            with self.subTest(repository=repository), patch('comfyctl.node_sources.download') as fetch, self.assertRaises(NodeSourceError):
                plan_source(repository, commit)
            fetch.assert_not_called()
        self.assertEqual(source_identity('o/r', SHA), ('o/r', SHA))

    def test_local_hash_is_mandatory_and_verified(self):
        data = archive([('repo/__init__.py', b'')])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.tar.gz'
            path.write_bytes(data)
            with self.assertRaisesRegex(NodeSourceError, 'requires --archive-sha256'):
                plan_source('o/r', SHA, archive=path)
            with self.assertRaisesRegex(NodeSourceError, 'does not match'):
                plan_source('o/r', SHA, 'b'*64, path)
            result = plan_source('o/r', SHA, hashlib.sha256(data).hexdigest(), path)
            self.assertEqual(result['repository'], 'o/r')

    def test_invalid_metadata_is_reported_without_silently_skipping_it(self):
        data = archive([('repo/__init__.py', b'invalid python !!!'),
                        ('repo/comfy-env.toml', b'bad = [ '), ('repo/binary.py', b'\xff')])
        self.assertEqual(analyze('o/r', SHA, data)['unparsed_text'], ['__init__.py', 'binary.py', 'comfy-env.toml'])

    def test_pyproject_gpu_dependency_is_included_in_review(self):
        data = archive([('repo/__init__.py', b''), ('repo/pyproject.toml', b'[project]\ndependencies=["xformers==0.0.35"]')])
        plan = analyze('o/r', SHA, data)
        self.assertEqual(plan['requirements'][0]['gpu_requirements'], ['xformers==0.0.35'])

    def test_cli_plan_is_available_without_managed_root(self):
        output = io.StringIO()
        with patch('comfyctl.node_sources.plan_source', return_value={'kind': 'test-plan'}) as inspect, patch('comfyctl.cli.os.geteuid', return_value=1000), redirect_stdout(output):
            self.assertEqual(main(['node', 'plan', 'o/r', '--commit', SHA]), 0)
        inspect.assert_called_once_with('o/r', SHA, None, None)
        self.assertEqual(json.loads(output.getvalue()), {'kind': 'test-plan'})


if __name__ == '__main__':
    unittest.main()
