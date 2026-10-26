import httpx

def app(environ, start_response):
    start_response("200 OK", [("content-type", "text/plain")])
    return [b"hello"]

client = httpx.Client(app=app)  # DOC-LITERAL

print("DOCS_OK")
