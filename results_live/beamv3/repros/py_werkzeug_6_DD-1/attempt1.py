from werkzeug.test import Client
from werkzeug.wrappers import Response

def app(environ, start_response):
    response = Response("ok")
    response.set_cookie("foo", "bar")
    return response(environ, start_response)

client = Client(app)
client.get("/")
cookie = client.get_cookie("foo")
assert cookie is not None
assert cookie.value == cookie.key, "docs describe value as the cookie key"  # DOC-LITERAL
print("DOCS_OK")
