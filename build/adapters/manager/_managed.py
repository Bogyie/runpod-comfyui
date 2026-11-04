"""Read-only Manager adapter. No legacy manager module is imported here."""
import hashlib
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

GUIDANCE = ('This image manages node and environment changes with comfyctl.\n'
    'Node install: comfyctl node add OWNER/REPO --name NAME --commit FULL_SHA '
    '--required-node NODE_CLASS_ID --smoke-workflow graph.json --defer\n'
    'Apply after queued work: comfyctl env apply --restart\n'
    'Disable: comfyctl node disable NAME --restart\n'
    'Recover: comfyctl env rollback --restart (or env reset --restart)\n'
    'Models: comfyctl model add URL --type TYPE\n'
    'Run these in the administrator terminal. Manager direct changes are disabled.')


def scan_pending(root):
    import folder_paths
    user = Path(folder_paths.get_user_directory())
    locations = [user/'__manager/startup-scripts', user/'default/ComfyUI-Manager/startup-scripts', root/'startup-scripts']
    items = []
    for directory in locations:
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.rglob('*')):
            if path.is_file() and not path.is_symlink():
                size = path.stat().st_size
                items.append({'path':str(path), 'bytes':size,
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if size <= 1024*1024 else None,
                    'action':'preserved-not-executed'})
    report = user/'comfyctl/manager/blocked-startup.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'policy':'managed-cli','pending':items,'guidance':GUIDANCE},indent=2)+'\n')
    if items:
        print('[ComfyUI-Manager] Preserved ' + str(len(items)) + ' legacy startup files; use comfyctl for changes.', flush=True)
    return items


def normalize_repository(value):
    if value.startswith('https://github.com/'):
        value = value[len('https://github.com/'):]
    value = value.removesuffix('.git').strip('/').lower()
    return 'comfy-org/comfyui-manager' if value == 'ltdrdata/comfyui-manager' else value


def active_nodes():
    sys.path.insert(0, '/opt/runtime/control')
    from selection import Store
    profile = Store().profile(os.environ['COMFYCTL_GENERATION_ID'], verify=False)
    return profile['nodes']


def safe_url(value):
    return value if isinstance(value,str) and urlparse(value).scheme == 'https' and urlparse(value).netloc else ''


def catalog(root):
    raw = json.loads((root/'custom-node-list.json').read_text())['custom_nodes']
    managed = {normalize_repository(item['repository']):item for item in active_nodes().values() if item.get('repository')}
    result, found = {}, set()
    for index, item in enumerate(raw):
        files = [safe_url(value) for value in item.get('files',[]) if safe_url(value)]
        key = files[0] if files else 'catalog-' + str(index)
        if key in result:
            key += '#' + str(index)
        repository = normalize_repository(files[0]) if files else ''
        definition = managed.get(repository)
        if definition:
            found.add(repository)
        result[key] = {**item, 'files':files, 'reference':safe_url(item.get('reference','')),
            'title':escape(str(item.get('title',key))), 'author':escape(str(item.get('author',''))),
            'description':escape(str(item.get('description',''))),
            'state':('enabled' if definition['enabled'] else 'disabled') if definition else 'not-installed',
            'version':'unknown','active_version':definition['commit'] if definition else None,
            'update-state':'false','managed':bool(definition)}
    for repository, item in managed.items():
        if repository in found:
            continue
        url = 'https://github.com/' + item['repository']
        result[url] = {'title':escape(item['directory']),'author':escape(item['repository'].split('/')[0]),
            'description':'Managed image node. Changes use comfyctl.', 'reference':url,'files':[url],
            'install_type':'git-clone','state':'enabled' if item['enabled'] else 'disabled',
            'version':'unknown','active_version':item['commit'],'update-state':'false','managed':True}
    return result


def install_routes(root):
    from aiohttp import web
    from server import PromptServer
    server = PromptServer.instance
    identity = json.loads((root/'_managed_identity.json').read_text())
    text = {'/manager/version':'V3.42','/manager/db_mode':'local','/manager/preview_method':'DISABLED',
            '/manager/policy/component':'workflow','/manager/policy/update':'stable-comfyui','/manager/share_option':'none'}
    readable = set(text) | {'/customnode/getlist','/customnode/getmappings','/customnode/installed',
        '/customnode/alternatives','/externalmodel/getlist','/manager/queue/status','/manager/notice',
        '/manager/startup_alerts','/manager/channel_url_list','/comfyctl/manager/status','/comfyctl/manager/help'}
    prefixes = ['/manager/','/customnode/','/snapshot/','/externalmodel/','/comfyui_manager/','/comfyctl/manager/']

    @web.middleware
    async def boundary(request, handler):
        path = request.path[4:] if request.path.startswith('/api/') else request.path
        if any(path.startswith(prefix) for prefix in prefixes):
            if request.method not in {'GET','HEAD'} or path not in readable or 'value' in request.query:
                return web.Response(text=GUIDANCE,status=403,headers={'X-Comfyctl-Policy':'managed-cli'})
        return await handler(request)

    server.app.middlewares.append(boundary)

    async def dispatch(request):
        path = request.path[4:] if request.path.startswith('/api/') else request.path
        if path in text:
            return web.Response(text=text[path])
        if path == '/customnode/getlist':
            return web.json_response({'channel':'local','node_packs':catalog(root)})
        if path == '/customnode/getmappings':
            return web.json_response(json.loads((root/'extension-node-map.json').read_text()))
        if path == '/customnode/installed':
            return web.json_response({key:item for key,item in catalog(root).items() if item['managed']})
        if path == '/customnode/alternatives':
            return web.json_response({})
        if path == '/externalmodel/getlist':
            return web.json_response(json.loads((root/'model-list.json').read_text()))
        if path == '/manager/queue/status':
            return web.json_response({'total_count':0,'done_count':0,'in_progress_count':0,'is_processing':False})
        if path == '/manager/startup_alerts':
            return web.json_response([])
        if path == '/manager/channel_url_list':
            return web.json_response({'selected':'local','list':['local::Bundled catalog']})
        if path in {'/manager/notice','/comfyctl/manager/help'}:
            return web.Response(text='<h3>Managed RunPod image</h3><p>Search uses the bundled Manager catalog. Install and recovery use the administrator CLI.</p><pre>'+escape(GUIDANCE)+'</pre>',content_type='text/html')
        return web.json_response({'mode':'managed-cli','manager_commit':identity['commit'],
            'catalog_entries':len(json.loads((root/'custom-node-list.json').read_text())['custom_nodes']),
            'direct_mutations':False,'guidance':GUIDANCE})

    for path in readable:
        server.routes.get(path)(dispatch)
