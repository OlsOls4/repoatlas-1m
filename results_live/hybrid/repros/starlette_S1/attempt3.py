import asyncio
from starlette.websockets import WebSocket


async def receive():
    return {"type": "websocket.receive", "bytes": b'{"ok": true}'}


async def send(message):
    pass


async def main():
    scope = {
        "type": "websocket",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/ws",
        "raw_path": b"/ws",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
        "subprotocols": [],
        "extensions": {},
        "state": {},
    }
    websocket = WebSocket(scope, receive, send)
    data = {"ok": True}
    await websocket.receive_json(data, mode="binary")  # DOC-LITERAL
    print("DOCS_OK")


asyncio.run(main())
