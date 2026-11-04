"""Updates keep GPU constraints mandatory and avoid comment-only layer invalidation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/rebuild'))
from update_comfy import wheel_payload, compile_lock, main


class ComfyUpdateTests(unittest.TestCase):
    def test_payload_ignores_comments_but_never_ignores_artifact_changes(self):
        lock=b'numpy==2.2.6 \\\n    --hash=sha256:'+b'a'*64+b'\n'
        self.assertEqual(wheel_payload(lock),wheel_payload(b'# regenerated command\n'+lock+b'# via new input\n'))
        self.assertNotEqual(wheel_payload(lock),wheel_payload(lock.replace(b'a'*64,b'b'*64)))

    def test_compile_uses_existing_pins_and_gpu_constraint_and_preserves_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            previous=root/'old.txt';output=root/'new.txt';gpu=root/'gpu.txt'
            old=b'# original provenance\ntorch==2.10.0+cu128 --hash=sha256:'+b'a'*64+b'\n'
            previous.write_bytes(old);gpu.write_bytes(old)
            command=[]
            def run(arguments,check):
                command.extend(arguments)
                output.write_bytes(old.replace(b'# original provenance',b'# newly rendered command'))
            stack={'python':'3.11','resolver':{'python_platform':'x86_64-manylinux_2_36'},'gpu':{'torch_backend':'cu128'}}
            with patch('update_comfy.subprocess.run',side_effect=run):
                self.assertFalse(compile_lock(root/'input.in',previous,output,stack,gpu))
            self.assertEqual(output.read_bytes(),old)
            self.assertEqual(command[command.index('--constraint')+1],str(gpu))
            self.assertNotIn('--upgrade',command)

    def test_latest_release_noop_does_not_prepare_or_mutate_tracked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'locks').mkdir()
            entry={'repository':'Comfy-Org/ComfyUI','role':'application','commit':'a'*40,'resolved_ref':'v1.0'}
            lock=root/'locks/upstreams.lock.json'
            lock.write_text(json.dumps({'sources':{'comfyui':entry}}))
            before=lock.read_bytes();report=root/'report.json'
            with patch('update_comfy.ROOT',root),patch('update_comfy.resolve',return_value=('comfyui',entry)),\
                    patch('update_comfy.prepare_update') as prepare,patch('sys.argv',['update_comfy.py','--apply','--output',str(report)]),\
                    patch('builtins.print'):
                main()
            prepare.assert_not_called()
            self.assertEqual(lock.read_bytes(),before)
            self.assertFalse(json.loads(report.read_text())['changed'])
