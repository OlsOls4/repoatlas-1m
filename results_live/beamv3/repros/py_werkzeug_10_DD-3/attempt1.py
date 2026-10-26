from io import BytesIO
from werkzeug.middleware.proxy_fix import ProxyFix


def app(environ, start_response):
    start_response("200 OK", [])
    return [b""]


wrapped = ProxyFix(app, x_for=1)
environ = {
    "REMOTE_ADDR": "127.0.0.1",
    "wsgi.url_scheme": "http",
    "HTTP_HOST": "localhost",
    "SCRIPT_NAME": "",
    "REQUEST_METHOD": "GET",
    "SERVER_NAME": "localhost",
    "SERVER_PORT": "80",
    "wsgi.input": BytesIO(b""),
    "wsgi.errors": BytesIO(),
}
wrapped(environ, lambda status, headers: None)
assert environ["werkzeug.proxy_fix.orig_REMOTE_ADDR"] == "127.0.0.1", "docs say original values are in werkzeug.proxy_fix.orig_{key}"  # DOC-LITERAL
print("DOCS_OK")
