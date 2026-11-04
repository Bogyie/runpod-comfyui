"""Worker construction must reject ABI/lock drift before changing a venv."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1]/'tools/rebuild/link_gpu_packages.py'
spec = importlib.util.spec_from_file_location('gpu_links',SCRIPT)
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)


class LinkValidationTests(unittest.TestCase):
    def test_system_site_packages_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix=Path(tmp)/'worker';prefix.mkdir()
            (prefix/'pyvenv.cfg').write_text('include-system-site-packages = true\n')
            with self.assertRaisesRegex(ValueError,'system site-packages'):
                links.link(prefix,Path(tmp)/'missing-lock')

    def test_gpu_version_mismatch_does_not_create_any_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefix=root/'worker';prefix.mkdir();site=prefix/'site';site.mkdir()
            source=root/'host-site';source.mkdir()
            (prefix/'pyvenv.cfg').write_text('include-system-site-packages = false\n')
            lock=root/'gpu.txt';lock.write_text('torch==2.10.0+cu128\n')
            dist=type('Dist',(),{'metadata':{'Name':'torch'},'version':'2.8.0','files':['torch/__init__.py']})()
            worker={'site':str(site),'prefix':str(prefix),'abi':sys.implementation.cache_tag}
            with patch.object(links.subprocess,'check_output',return_value=json.dumps(worker)), \
                 patch.object(links.sysconfig,'get_path',return_value=str(source)), \
                 patch.object(links.importlib.metadata,'distributions',return_value=[dist]):
                with self.assertRaisesRegex(ValueError,'does not match lock'):
                    links.link(prefix,lock)
            self.assertEqual(list(site.iterdir()),[])
            self.assertFalse((prefix/'gpu-links.json').exists())

    def test_different_python_abi_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix=Path(tmp)/'worker';prefix.mkdir()
            (prefix/'pyvenv.cfg').write_text('include-system-site-packages = false\n')
            worker={'site':str(prefix/'site'),'prefix':str(prefix),'abi':'cpython-999'}
            with patch.object(links.subprocess,'check_output',return_value=json.dumps(worker)):
                with self.assertRaisesRegex(ValueError,'ABI'):
                    links.link(prefix,Path(tmp)/'not-read')
