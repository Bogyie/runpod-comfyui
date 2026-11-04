"""Live V1 metadata callbacks in a separate CPU-only comfy-env worker.

Installed as comfy_env.isolation.managed_metadata by the guarded SDK patch.
Node imports stay in their private interpreter; compute workers have a separate
pool and cannot hold the metadata IPC lock during a long GPU operation.
"""
import atexit
import asyncio
import base64
from contextvars import ContextVar
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import threading

_POOL = {}
_LOCK = threading.RLock()
_SCHEMAS = ContextVar('comfyctl_request_schemas',default=None)
_HTTP_INSTALLED = False


def plain(value):
    if value is None:
        return None
    for kind in (bool, str, int, float, bytes):
        if isinstance(value, kind):
            return kind(value)
    if isinstance(value, dict):
        return {plain(key):plain(item) for key,item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(plain(item) for item in value) if type(value) in (list,tuple) else [plain(item) for item in value]
    raise TypeError('Unsupported metadata value: ' + type(value).__name__)


def scan(package):
    """Runs in the CPU worker, with the same paths as actual node execution."""
    module = importlib.import_module(package)
    nodes = {}
    for name, cls in getattr(module, 'NODE_CLASS_MAPPINGS', {}).items():
        meta = {target:getattr(cls, attr, default) for target,attr,default in [
            ('function','FUNCTION',None),('category','CATEGORY',''),('output_node','OUTPUT_NODE',False),
            ('return_types','RETURN_TYPES',()),('return_names','RETURN_NAMES',()),
            ('output_is_list','OUTPUT_IS_LIST',None),('input_is_list','INPUT_IS_LIST',None)]}
        meta.update(module_name=cls.__module__,class_name=cls.__name__,managed_callbacks={},managed_package=package)
        for method in ['IS_CHANGED','VALIDATE_INPUTS']:
            callback = getattr(cls, method, None)
            if callable(callback):
                meta['managed_callbacks'][method] = [
                    {'name':param.name,'kind':param.kind.name,'default':param.default is not inspect.Parameter.empty}
                    for param in inspect.signature(callback).parameters.values()]
        if callable(getattr(cls,'INPUT_TYPES',None)):
            try:
                meta['input_types'] = cls.INPUT_TYPES()
            except Exception as error:
                meta.update(input_types={'required':{}},input_types_error=str(error))
        nodes[name] = meta
    routes = list(getattr(module,'ROUTES',[]))
    for name, submodule in list(sys.modules.items()):
        if name.startswith(package+'.'):
            for route in getattr(submodule,'ROUTES',[]):
                routes.append(dict(route,module=route.get('module',name)))
    routes = [dict(route,module=route.get('module',package)) for route in routes]
    return plain({'nodes':nodes,'display':getattr(module,'NODE_DISPLAY_NAME_MAPPINGS',{}),'routes':routes})


def schemas(package):
    result = {}
    for cls in importlib.import_module(package).NODE_CLASS_MAPPINGS.values():
        key = cls.__module__+'::'+cls.__name__
        try:
            result[key] = {'schema':plain(cls.INPUT_TYPES())}
        except Exception as error:
            result[key] = {'error':str(error)}
    return result


def install_http_context():
    global _HTTP_INSTALLED
    if _HTTP_INSTALLED:
        return
    from aiohttp import web
    from server import PromptServer
    @web.middleware
    async def request_schemas(request, handler):
        token = _SCHEMAS.set({})
        try:
            return await handler(request)
        finally:
            _SCHEMAS.reset(token)
    PromptServer.instance.app.middlewares.append(request_schemas)
    _HTTP_INSTALLED = True


def invoke(node_module, class_name, method, inputs):
    if method not in {'INPUT_TYPES','IS_CHANGED','VALIDATE_INPUTS'}:
        raise ValueError('Unsupported metadata callback')
    callback = getattr(getattr(importlib.import_module(node_module), class_name), method)
    result = callback(**inputs)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return plain(result)


def pack(value):
    value = plain(value)
    if isinstance(value,dict):
        return ['dict',[[pack(key),pack(item)] for key,item in value.items()]]
    if isinstance(value,(list,tuple)):
        return ['tuple' if isinstance(value,tuple) else 'list',[pack(item) for item in value]]
    if isinstance(value,bytes):
        return ['bytes',base64.b64encode(value).decode('ascii')]
    if isinstance(value,float):
        return ['float',value.hex()]
    return ['scalar',value]


def unpack(value):
    kind, data = value
    if kind == 'dict':return {unpack(key):unpack(item) for key,item in data}
    if kind == 'tuple':return tuple(unpack(item) for item in data)
    if kind == 'list':return [unpack(item) for item in data]
    if kind == 'bytes':return base64.b64decode(data,validate=True)
    if kind == 'float':return float.fromhex(data)
    if kind == 'scalar':return data
    raise ValueError('Unsupported metadata wire value')


def dispatch_json(payload):
    request = unpack(json.loads(payload))
    functions = {'scan':scan,'schemas':schemas,'invoke':invoke}
    result = functions[request['function']](**request['arguments'])
    return json.dumps(pack(result),allow_nan=False)


def wire_call(worker, function, arguments, timeout):
    # Only strings cross this socket. Do not use call_module's tensor decoder
    # or its process-global FD/cache cleanup while compute RPC is in flight.
    payload = json.dumps(pack({'function':function,'arguments':arguments}),allow_nan=False)
    with worker._lock:
        worker._ensure_started()
        worker._call_counter += 1
        response = worker._send_request({'type':'call_module','call_id':worker._call_counter,
            'module':__name__,'func':'dispatch_json','kwargs':{'payload':payload}},timeout)
        if response.get('status') != 'ok':
            raise RuntimeError('Metadata callback failed: '+str(response.get('error','unknown error')))
        if not isinstance(response.get('result'),str):
            raise TypeError('Metadata worker returned a non-JSON payload')
        return unpack(json.loads(response['result']))


def shutdown():
    with _LOCK:
        for worker in _POOL.values():
            try:
                worker.shutdown()
            except Exception:
                pass
        _POOL.clear()


atexit.register(shutdown)


def worker_for(env_dir, working_dir, sys_path, env_vars, *, pooled=True):
    # register_nodes supplies the private site and package root; scans use the
    # same canonical paths so registration and live callbacks share one worker.
    sys_path = [str(Path(env_dir)/'lib/python3.11/site-packages'),str(working_dir)]
    variables = dict(env_vars or {}, COMFY_CPU='1', CUDA_VISIBLE_DEVICES='',
                     COMFYCTL_METADATA_WORKER='1', COMFYCTL_METADATA_PACKAGE_ROOT=str(working_dir),
                     COMFYCTL_WORKER_ATTENTION='pytorch')
    key = json.dumps([str(env_dir),str(working_dir),list(map(str,sys_path)),variables],sort_keys=True)
    with _LOCK:
        worker = _POOL.get(key) if pooled else None
        if worker is None:
            from .workers.subprocess import SubprocessWorker
            worker = SubprocessWorker(python=Path(env_dir)/'bin/python',working_dir=working_dir,
                sys_path=sys_path,env=variables,name='metadata-'+Path(working_dir).name,health_check_timeout=60)
            if pooled:
                _POOL[key] = worker
    return worker


def call(env_dir, working_dir, sys_path, env_vars, function, **kwargs):
    # A candidate runs beside the active service. Retaining another full pool
    # doubles Python/Torch RAM. Execute the same callbacks in short-lived CPU
    # workers during validation; production keeps its independent warm pool.
    pooled = (os.environ.get('COMFYCTL_VALIDATING') != '1' or
              Path(env_dir).is_relative_to('/workspace/runtime/generations'))
    worker = worker_for(env_dir,working_dir,sys_path,env_vars,pooled=pooled)
    try:
        return wire_call(worker,function,kwargs,timeout=120 if not pooled else 30)
    except BaseException:
        process = worker._process
        if pooled and (worker._shutdown or (process is not None and process.poll() is not None)):
            with _LOCK:
                for key in [key for key,value in _POOL.items() if value is worker]:
                    del _POOL[key]
            with worker._lock:
                # The pinned SDK marks transport failure as shutdown before
                # cleaning its socket/temp files. Finish that cleanup once.
                worker._shutdown = False
                worker.shutdown()
        raise
    finally:
        if not pooled:
            worker.shutdown()


def fetch(env_dir, node_dir, package, working_dir, env_vars):
    # Import once at startup; callbacks query this CPU process afresh instead of
    # returning a stale pickle. No file listing is persisted across restarts.
    install_http_context()
    result = call(env_dir,working_dir,[str(working_dir)],env_vars,'scan',package=package)
    print('[comfy-env] Live CPU metadata: '+package+' ('+str(len(result['nodes']))+' nodes)',file=sys.stderr,flush=True)
    return result


def normalize_inputs(schema):
    result = {key:dict(value) for key,value in schema.items()}
    for section in ['required','optional']:
        for name,info in list(result.get(section,{}).items()):
            if isinstance(info,(list,tuple)) and info and info[0]=='COMFY_DYNAMICCOMBO_V3':
                options = info[1] if len(info)>1 and isinstance(info[1],dict) else {}
                for option in options.get('options',[]):
                    for children in ['required','optional']:
                        for child,value in option.get('inputs',{}).get(children,{}).items():
                            result.setdefault('optional',{})[name+'.'+child] = value
    if 'hidden' in result:
        result['hidden'] = {key:value[0] if isinstance(value,(list,tuple)) and len(value)==1 else value
                            for key,value in result['hidden'].items()}
    return result


def bind(attrs, meta, env_dir, package_root, sys_path, env_vars):
    def remote(method, /, **inputs):
        context = _SCHEMAS.get()
        if method == 'INPUT_TYPES' and context is not None:
            key = (str(env_dir),str(package_root),json.dumps(env_vars,sort_keys=True),meta['managed_package'])
            if key not in context:
                context[key] = call(env_dir,package_root,sys_path,env_vars,'schemas',package=meta['managed_package'])
            item = context[key][meta['module_name']+'::'+meta['class_name']]
            if 'error' in item:
                raise RuntimeError('INPUT_TYPES failed: '+item['error'])
            return item['schema']
        # Worker errors remain visible. Never substitute stale schemas or a
        # successful validation response after a callback failed.
        return call(env_dir,package_root,sys_path,env_vars,'invoke',node_module=meta['module_name'],
                    class_name=meta['class_name'],method=method,inputs=inputs)

    @classmethod
    def input_types(cls):
        return normalize_inputs(remote('INPUT_TYPES'))
    attrs['INPUT_TYPES'] = input_types
    for method, parameters in meta.get('managed_callbacks',{}).items():
        def make_callback(method):
            def callback(**inputs):
                return remote(method, **inputs)
            return callback
        callback = make_callback(method)
        callback.__name__ = method
        callback.__signature__ = inspect.Signature([
            inspect.Parameter(param['name'],getattr(inspect.Parameter,param['kind']),
                              default=None if param['default'] else inspect.Parameter.empty)
            for param in parameters])
        attrs[method] = staticmethod(callback)
