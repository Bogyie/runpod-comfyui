"""Reproduce cross-thread PoolIPC handle corruption without requiring a GPU."""
import ast
from pathlib import Path
import sys
import threading
import types
import typing
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/rebuild'))
from apply_comfy_env_patch import transformed


class WorkerPoolContextTests(unittest.TestCase):
    def exercise(self, patched):
        root=ROOT/'.work/comfy-env-0.3.89/comfy_env/isolation/workers'
        if not (root/'subprocess.py').is_file():self.skipTest('reproduce pinned artifact first')
        parent=(root/'_ipc_parent.py').read_bytes();caller=(root/'subprocess.py').read_bytes()
        if patched:
            parent=transformed('isolation/workers/_ipc_parent.py',parent)
            caller=transformed('isolation/workers/subprocess.py',caller)
        ipc=types.ModuleType('ipc_context_test')
        tree=ast.parse(parent)
        selected=[node for node in tree.body if
            (isinstance(node,ast.ImportFrom) and node.module=='contextvars') or
            (isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='_active_worker_pool' for target in node.targets)) or
            (isinstance(node,ast.FunctionDef) and node.name=='_from_shm')]
        ipc._deserialize_pool_ipc=lambda obj,pool:pool
        exec(compile(ast.Module(body=selected,type_ignores=[]),'real-pool-decode','exec'),ipc.__dict__)
        barrier=threading.Barrier(2)
        def decode(value):
            barrier.wait(timeout=5)
            return ipc._from_shm(value)
        cls=next(node for node in ast.parse(caller).body if isinstance(node,ast.ClassDef) and node.name=='SubprocessWorker')
        method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='call_module')
        scope={'Optional':typing.Optional,'Any':typing.Any,'_ipc_parent':ipc,'_from_shm':decode,
               '_cleanup_shm':lambda *args:None,'_cleanup_parent_fds':lambda *args:None,'_cleanup_ipc_cache':lambda:None,
               '_parent_fd_registry':[]}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'real-worker-call','exec'),scope)
        results={};errors=[]
        def call(name):
            worker=types.SimpleNamespace(_lock=threading.RLock(),_ensure_started=lambda:None,_call_counter=0,
                _worker_pool=name,_send_request=lambda request,timeout:{'status':'ok','result':{'__type__':'PoolIPC'}})
            try:
                results[name]=scope['call_module'](worker,'module','function')
                if patched:self.assertIsNone(ipc._active_worker_pool.get())
            except BaseException as error:errors.append(str(error))
        threads=[threading.Thread(target=call,args=(name,)) for name in ['compute','metadata']]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        return results,errors

    def test_original_race_reproduces_and_context_patch_isolates_each_call(self):
        original,errors=self.exercise(False)
        self.assertTrue(errors or original!={'compute':'compute','metadata':'metadata'})
        result,errors=self.exercise(True)
        self.assertEqual(errors,[])
        self.assertEqual(result,{'compute':'compute','metadata':'metadata'})


if __name__=='__main__':unittest.main()
