"""Run in an owned test container; assert FastPreview delivers actual PNG bytes."""
import asyncio
import hashlib
import io
import json
import time
import uuid
import aiohttp
from PIL import Image


async def main():
    client=uuid.uuid4().hex
    base='http://127.0.0.1:8188'
    graph={'1':{'class_type':'EmptyImage','inputs':{'width':64,'height':32,'batch_size':1,'color':0x0f2030}},
           '2':{'class_type':'FastPreview','inputs':{'image':['1',0],'format':'PNG','max_size':128}}}
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(base+'/ws?clientId='+client) as ws:
            async with session.post(base+'/prompt',json={'prompt':graph,'client_id':client}) as response:
                submitted=await response.json()
            if submitted.get('node_errors'):raise RuntimeError(str(submitted))
            end=time.monotonic()+60
            preview=None
            while time.monotonic()<end:
                msg=await ws.receive(timeout=20)
                if msg.type==aiohttp.WSMsgType.BINARY:
                    data=msg.data
                    if int.from_bytes(data[:4],'big')!=1 or int.from_bytes(data[4:8],'big')!=2:
                        raise RuntimeError('Unexpected KJ preview wire header')
                    image=Image.open(io.BytesIO(data[8:]));image.load()
                    if image.size!=(64,32) or image.getpixel((0,0))!=(15,32,48):raise RuntimeError('KJ websocket preview image differs from graph input')
                    preview={'event':1,'format':'PNG','width':64,'height':32,'pixel':[15,32,48],'sha256':hashlib.sha256(data[8:]).hexdigest()}
                    break
            if preview is None:raise RuntimeError('No KJ binary preview received')
            while time.monotonic()<end:
                async with session.get(base+'/history/'+submitted['prompt_id']) as response:history=await response.json()
                if submitted['prompt_id'] in history:
                    status=history[submitted['prompt_id']]['status']
                    if status['status_str']!='success':raise RuntimeError(str(status))
                    print(json.dumps({'status':'passed','preview':preview,'history_status':status}),flush=True)
                    return
                await asyncio.sleep(.25)
            raise RuntimeError('KJ FastPreview graph did not finish')


asyncio.run(main())
