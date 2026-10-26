import inspect

import httpx

# DOC-LITERAL-BEGIN
transport = httpx.HTTPTransport(uds=None, local_address=None, retries=0)
# DOC-LITERAL-END

async_transport_signature = inspect.signature(httpx.AsyncHTTPTransport.__init__)
transport_signature = inspect.signature(httpx.HTTPTransport.__init__)
assert "socket_options" in transport_signature.parameters
assert "socket_options" in async_transport_signature.parameters
assert "* socket_options: typing.Iterable[SOCKET_OPTION] | None" in (httpx._transports.default.__doc__ or "")
print("DOCS_OK")
