from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient


async def endpoint(websocket):
    await websocket.accept()
    await websocket.send_bytes(b'{"ok": true}')
    await websocket.close()


app = Starlette(routes=[WebSocketRoute("/ws", endpoint)])
client = TestClient(app)
with client.websocket_connect("/ws") as websocket:
    data = None
    result = websocket.receive_json(data, mode="binary")  # DOC-LITERAL
    assert result == {"ok": True}, "docs say this receives JSON over binary frames"
print("DOCS_OK")
