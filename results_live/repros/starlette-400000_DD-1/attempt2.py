from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient

async def endpoint(websocket):
    await websocket.accept()
    data = b'{"ok": true}'
    await websocket.receive_json(data, mode="binary")  # DOC-LITERAL
    await websocket.close()

app = Starlette(routes=[WebSocketRoute("/ws", endpoint)])
client = TestClient(app)
with client.websocket_connect("/ws") as websocket:
    websocket.send_bytes(b'{"ok": true}')
print("DOCS_OK")
