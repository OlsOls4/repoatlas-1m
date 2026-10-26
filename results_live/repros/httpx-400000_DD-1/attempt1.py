import httpx

class HTTPSRedirect(httpx.BaseTransport):
    def handle_request(self, request):
        url = request.url.copy_with(scheme="https")
        return httpx.Response(303, headers={"Location": str(url)})

# DOC-LITERAL-BEGIN
transport = httpx.Mounts({
    'http://': HTTPSRedirect(),
    'https://': httpx.HTTPTransport()
})
client = httpx.Client(transport=transport)
# DOC-LITERAL-END

print("DOCS_OK")
