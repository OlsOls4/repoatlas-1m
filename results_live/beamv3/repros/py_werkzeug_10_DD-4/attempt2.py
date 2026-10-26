import http.client
import werkzeug.middleware.http_proxy as proxy_module

recorded = {}

class FakeConnection:
    def __init__(self, *args, **kwargs):
        pass

    def request(self, method, path, body=None, headers=None):
        recorded["path"] = path

    def getresponse(self):
        class Response:
            status = 200
            reason = "OK"

            def getheaders(self):
                return [("Content-Type", "text/plain")]

            def read(self, size=-1):
                return b""

            def close(self):
                pass

        return Response()

    def close(self):
        pass

for attr in list(proxy_module.__dict__):
    if "Connection" in attr and isinstance(proxy_module.__dict__[attr], type):
        setattr(proxy_module, attr, FakeConnection)
http.client.HTTPConnection = FakeConnection
http.client.HTTPSConnection = FakeConnection

from werkzeug.middleware.http_proxy import ProxyMiddleware
from werkzeug.test import Client


def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"ok"]

app = ProxyMiddleware(app, {"/static": {"target": "http://localhost:5001/"}})  # DOC-LITERAL
client = Client(app)
response = client.get("/static/foo.txt")
assert recorded.get("path") == "/foo.txt", "docs say the /static/ prefix is removed"  # DOC-LITERAL
print("DOCS_OK")
