import httpx


def app(environ, start_response):
    start_response("200 OK", [("content-type", "text/plain")])
    return [b"ok"]


client = httpx.Client(app=app)  # DOC-LITERAL
print("DOCS_OK")
