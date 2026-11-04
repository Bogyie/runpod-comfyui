import hashlib
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("snapshot", Path(__file__).parents[1] / "tools/rebuild/snapshot_upstreams.py")
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


def archive(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for name, body, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/escape.py"
                tar.addfile(info)
            else:
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
    return stream.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_installer_is_data_and_links_are_not_extracted(self):
        body = b"raise RuntimeError('must never execute')\n"
        data = archive([("root/install.py", body, "file"), ("root/link.py", b"", "link")])
        with tempfile.TemporaryDirectory() as tmp:
            files = snapshot.inspect_archive(data, Path(tmp))
            self.assertEqual(files, {"install.py": hashlib.sha256(body).hexdigest()})
            self.assertFalse((Path(tmp) / "link.py").exists())

    def test_traversal_is_rejected(self):
        for name in ["root/../../escape.py", "/absolute.py"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                snapshot.inspect_archive(archive([(name, b"bad", "file")]))

    def test_existing_symlink_cannot_redirect_writes(self):
        data = archive([("root/pkg/install.py", b"bad", "file")])
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            (Path(tmp) / "pkg").symlink_to(outside)
            with self.assertRaises(ValueError):
                snapshot.inspect_archive(data, Path(tmp))


if __name__ == "__main__":
    unittest.main()
