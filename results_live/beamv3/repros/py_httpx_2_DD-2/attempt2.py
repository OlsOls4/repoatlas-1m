import inspect

import httpx

# DOC-LITERAL-BEGIN
transport = httpx.HTTPTransport(uds=None, local_address=None, retries=0)
# DOC-LITERAL-END

# DOC-LITERAL
assert "socket_options" in inspect.signature(httpx.HTTPTransport.__init__).parameters
# DOC-LITERAL
assert "socket_options" in inspect.signature(httpx.AsyncHTTPTransport.__init__).parameters
# DOC-LITERAL
assert "* socket_options: typing.Iterable[SOCKET_OPTION] | None" in (httpx._transports.default.__doc__ or "")
print("DOCS_OK")
