"""Legacy mutation entry points cannot execute their original payloads."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/rebuild'))
from apply_manager_adapter import apply, COMMIT


def load(path):
    spec=importlib.util.spec_from_file_location('manager_adapter_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class ManagerAdapterTests(unittest.TestCase):
    def test_revision_and_file_drift_are_rejected_before_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'__init__.py';source.write_text('original = True\n')
            with self.assertRaisesRegex(ValueError,'revision'):
                apply(root,{'commit':'other'})
            with self.assertRaisesRegex(ValueError,'Python source'):
                apply(root,{'commit':COMMIT,'files':{'__init__.py':'0'*64}})
            self.assertEqual(source.read_text(),'original = True\n')

    def test_cli_backend_and_repair_payloads_are_ineligible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);marker=root/'unexpected'
            source={}
            for name in ['__init__.py','prestartup_script.py','cm-cli.py','glob/manager_util.py','glob/manager_server.py','glob/manager_core.py']:
                path=root/name;path.parent.mkdir(exist_ok=True)
                data=('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n').encode()
                path.write_bytes(data);source[name]=hashlib.sha256(data).hexdigest()
            (root/'js').mkdir()
            for name in ['custom-nodes-manager.js','model-manager.js']:
                (root/'js'/name).write_text('This action is not allowed with this security level configuration.\n'*2)
            apply(root,{'commit':COMMIT,'files':source})
            for name in ['glob/manager_util.py','glob/manager_server.py','glob/manager_core.py']:
                with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'comfyctl'):
                    load(root/name)
            with self.assertRaisesRegex(SystemExit,'comfyctl'):
                load(root/'cm-cli.py')
            self.assertFalse(marker.exists())

    def test_pending_scripts_are_preserved_and_reported_without_execution(self):
        module=load(ROOT/'build/adapters/manager/_managed.py')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);user=root/'user';queue=user/'__manager/startup-scripts'
            queue.mkdir(parents=True);script=queue/'install-scripts.txt'
            data=b"['/tmp', '#LAZY-INSTALL-SCRIPT', 'pip', 'install', 'torch==0']\n"
            script.write_bytes(data)
            fake=types.SimpleNamespace(get_user_directory=lambda:str(user))
            with patch.dict(sys.modules,{'folder_paths':fake}):
                report=module.scan_pending(root)
            self.assertEqual(script.read_bytes(),data)
            self.assertEqual(report[0]['action'],'preserved-not-executed')
            self.assertEqual(report[0]['sha256'],hashlib.sha256(data).hexdigest())


if __name__=='__main__':unittest.main()
