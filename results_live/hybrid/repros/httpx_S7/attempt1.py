import requests
from requests.adapters import HTTPAdapter

class NoNetworkAdapter(HTTPAdapter):
    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response._content = b""
        return response

session = requests.Session()
session.mount("http://", NoNetworkAdapter())
session.mount("https://", NoNetworkAdapter())

request = requests.Request("GET", "http://example.test/").prepare()
response = session.send(request, allow_redirects=False)  # DOC-LITERAL
assert response.status_code == 200
print("DOCS_OK")
