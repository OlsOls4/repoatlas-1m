import httpx

# DOC-LITERAL-BEGIN
class HTTPSRedirectTransport(httpx.BaseTransport):
    """
    A transport that always redirects to HTTPS.
    """

    def handle_request(self, method, url, headers, stream, extensions):
        scheme, host, port, path = url
        if port is None:
            location = b"https://%s%s" % (host, path)
        else:
            location = b"https://%s:%d%s" % (host, port, path)
        stream = httpx.ByteStream(b"")
        headers = [(b"location", location)]
        extensions = {}
        return 303, headers, stream, extensions

mounts = {'http://': HTTPSRedirectTransport()}
client = httpx.Client(mounts=mounts)
response = client.get("http://example.com/")
assert response.status_code == 303, "documented transport should return a 303 redirect"
# DOC-LITERAL-END

print("DOCS_OK")
