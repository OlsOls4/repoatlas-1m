import asyncio
from starlette.websockets import WebSocket

async def main():
    async def receive():
        return {"type": "websocket.receive", "bytes": b'{"ok": true}'}
    async def send(message):
        pass
    scope = {"type": "websocket", "path": "/ws", "headers": []}
    websocket = WebSocket(scope, receive, send)
    await websocket.accept()
    data = b'{"ok": true}'
    await websocket.receive_json(data, mode="binary")  # DOC-LITERAL
    print("DOCS_OK")

asyncio.run(main())
