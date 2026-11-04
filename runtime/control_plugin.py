"""Read-only runtime introspection and a root-file-controlled prompt admission gate."""
import os
from pathlib import Path

NODE_CLASS_MAPPINGS = {}

if os.environ.get('COMFYCTL_STORAGE_DIR'):
    from aiohttp import web
    from server import PromptServer

    server = PromptServer.instance
    inflight = 0
    maintenance = Path('/workspace/runtime/control/maintenance.json')

    def blocked():
        try:
            return maintenance.exists() and os.environ.get('COMFYCTL_VALIDATING') != '1'
        except OSError:
            return True

    @web.middleware
    async def admission(request, handler):
        global inflight
        prompt = request.method == 'POST' and request.path in {'/prompt', '/api/prompt'}
        if prompt and blocked():
            return web.json_response({'error': 'Runtime transition in progress; retry after completion'},
                                     status=503, headers={'Retry-After': '5'})
        if prompt:
            inflight += 1
        try:
            return await handler(request)
        finally:
            if prompt:
                inflight -= 1

    server.app.middlewares.append(admission)

    @server.routes.get('/comfyctl/runtime/idle')
    async def idle(request):
        running, pending = server.prompt_queue.get_current_queue_volatile()
        return web.json_response({'running': len(running), 'pending': len(pending), 'inflight': inflight,
                                  'maintenance': blocked(), 'generation_id': os.environ.get('COMFYCTL_GENERATION_ID'),
                                  'runtime_id': os.environ['COMFYCTL_RUNTIME_ID'], 'pid': os.getpid()})
