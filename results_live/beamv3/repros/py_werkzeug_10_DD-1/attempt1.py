import io, sys
from werkzeug.middleware.proxy_fix import ProxyFix

def environ():
    return {
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "SERVER_NAME": "original.example",
        "SERVER_PORT": "80",
        "HTTP_HOST": "original.example",
        "HTTP_X_FORWARDED_HOST": "forwarded.example:8080",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiproc": False,
        "wsgi.run_once": False,
    }

captured = {}
def app(environ, start_response):
    captured.update(environ)
    start_response("200 OK", [])
    return [b""]

proxy = ProxyFix(app, x_host=1)
proxy(environ(), lambda status, headers: None)

assert captured["HTTP_HOST"] == "forwarded.example:8080"  # DOC-LITERAL
assert captured["SERVER_NAME"] == "forwarded.example"  # DOC-LITERAL
assert captured["SERVER_PORT"] == "8080"  # DOC-LITERAL
print("DOCS_OK")
