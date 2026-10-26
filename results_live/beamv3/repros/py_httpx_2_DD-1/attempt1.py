import inspect
from httpx._content import encode_request

parameters = list(inspect.signature(encode_request).parameters)  # DOC-LITERAL
for name in parameters:  # DOC-LITERAL
    assert name in (inspect.getdoc(encode_request) or ""), f"docstring omits {name!r}"  # DOC-LITERAL
print("DOCS_OK")
