"""Live callback schemas and signatures without importing node dependencies."""
import importlib.util
import inspect
import math
import os
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch, Mock

SOURCE=Path(__file__).resolve().parents[1]/'tools/rebuild/managed_metadata.py'
spec=importlib.util.spec_from_file_location('managed_metadata_test',SOURCE)
metadata=importlib.util.module_from_spec(spec);spec.loader.exec_module(metadata)


class ManagedMetadataTests(unittest.TestCase):
    def test_dead_metadata_transport_is_removed_and_cleaned(self):
        worker=Mock();worker._process=Mock();worker._process.poll.return_value=-9
        worker._shutdown=True;worker._lock=threading.RLock()
        with patch.dict(metadata._POOL,{'dead':worker},clear=True),patch.object(metadata,'worker_for',return_value=worker),patch.object(metadata,'wire_call',side_effect=RuntimeError('transport died')):
            with self.assertRaisesRegex(RuntimeError,'transport died'):
                metadata.call(Path('/opt/workers/base'),Path('/code'),[],{},'scan')
            self.assertEqual(metadata._POOL,{})
            worker.shutdown.assert_called_once()

    def test_candidate_base_workers_release_ram_and_added_workers_keep_callback_state(self):
        worker=Mock();worker._process=None;worker._shutdown=False
        with patch.dict(os.environ,{'COMFYCTL_VALIDATING':'1'}),patch.object(metadata,'worker_for',return_value=worker) as factory,patch.object(metadata,'wire_call',return_value={'ok':True}) as wire:
            self.assertEqual(metadata.call(Path('/opt/workers/base'),Path('/code'),[],{},'scan'),{'ok':True})
            self.assertFalse(factory.call_args.kwargs['pooled'])
            worker.shutdown.assert_called_once()
            worker.reset_mock()
            metadata.call(Path('/workspace/runtime/generations/abc/environment-node/venv'),Path('/code'),[],{},'scan')
            self.assertTrue(factory.call_args.kwargs['pooled'])
            worker.shutdown.assert_not_called()
            wire.side_effect=RuntimeError('callback failed')
            with self.assertRaisesRegex(RuntimeError,'callback failed'):
                metadata.call(Path('/opt/workers/base'),Path('/code'),[],{},'scan')
            worker.shutdown.assert_called_once()

    def test_callbacks_are_live_signature_faithful_and_async_errors_are_visible(self):
        state={'files':['old'],'version':1}
        class Example:
            FUNCTION='run';RETURN_TYPES=('STRING',)
            @classmethod
            def INPUT_TYPES(cls):return {'required':{'file':(list(state['files']),)}}
            @classmethod
            def IS_CHANGED(cls,file):return (file,state['version'])
            @classmethod
            async def VALIDATE_INPUTS(cls,file,method='default',**kwargs):
                return True if file in state['files'] else 'missing file'
        module=types.ModuleType('metadata_fixture');module.NODE_CLASS_MAPPINGS={'Example':Example}
        Example.__module__=module.__name__;module.Example=Example
        class Worker:
            _lock=threading.RLock();_call_counter=0;_process=None;_shutdown=False
            def _ensure_started(self):pass
            def _send_request(self, request, timeout):
                self_request=request['kwargs']
                assert list(self_request)==['payload'] and isinstance(self_request['payload'],str)
                return {'status':'ok','result':metadata.dispatch_json(self_request['payload'])}
        with patch.dict(sys.modules,{module.__name__:module}),patch.object(metadata,'worker_for',return_value=Worker()):
            info=metadata.scan(module.__name__)['nodes']['Example']
            attrs={};metadata.bind(attrs,info,Path('/private'),Path('/code'),[],{})
            proxy=type('Proxy',(),attrs)
            self.assertEqual(inspect.getfullargspec(proxy.VALIDATE_INPUTS).args,['file','method'])
            self.assertEqual(inspect.getfullargspec(proxy.VALIDATE_INPUTS).varkw,'kwargs')
            self.assertEqual(proxy.INPUT_TYPES()['required']['file'][0],['old'])
            state['files'].append('new');state['version']=2
            self.assertIn('new',proxy.INPUT_TYPES()['required']['file'][0])
            self.assertEqual(proxy.IS_CHANGED(file='new'),('new',2))
            self.assertTrue(proxy.VALIDATE_INPUTS(file='new',method='named-input'))
            self.assertEqual(proxy.VALIDATE_INPUTS(file='missing'),'missing file')
            with self.assertRaises(ValueError):metadata.invoke(module.__name__,'Example','run',{})
            token=metadata._SCHEMAS.set({})
            try:
                self.assertIn('new',proxy.INPUT_TYPES()['required']['file'][0])
                state['files'].append('next-request')
                self.assertNotIn('next-request',proxy.INPUT_TYPES()['required']['file'][0])
            finally:
                metadata._SCHEMAS.reset(token)
            token=metadata._SCHEMAS.set({})
            try:
                self.assertIn('next-request',proxy.INPUT_TYPES()['required']['file'][0])
            finally:
                metadata._SCHEMAS.reset(token)

    def test_schema_normalization_preserves_dynamic_children_and_hidden_values(self):
        schema={'required':{'backend':('COMFY_DYNAMICCOMBO_V3',{'options':[{'inputs':{'required':{'size':('INT',)}}}]})},
                'hidden':{'unique_id':('UNIQUE_ID',)}}
        result=metadata.normalize_inputs(schema)
        self.assertEqual(result['optional']['backend.size'],('INT',))
        self.assertEqual(result['hidden']['unique_id'],'UNIQUE_ID')
        self.assertNotIn('optional',schema)

    def test_metadata_cannot_smuggle_node_objects_into_host(self):
        class Text(str):pass
        self.assertIs(type(metadata.plain(Text('*'))),str)
        with self.assertRaises(TypeError):metadata.plain(object())
        value={('tuple-key',1):[b'bytes',('nested',None,True,3.5)]}
        self.assertEqual(metadata.unpack(metadata.pack(value)),value)
        first=metadata.unpack(metadata.pack(float('nan')))
        second=metadata.unpack(metadata.pack(float('nan')))
        self.assertTrue(math.isnan(first) and math.isnan(second))
        self.assertIsNot(first,second)


if __name__=='__main__':unittest.main()
