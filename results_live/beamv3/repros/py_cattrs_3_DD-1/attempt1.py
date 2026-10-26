import base64
from cattrs.preconf.ujson import make_converter

converter = make_converter()
assert converter.unstructure(b"hello") == base64.b64encode(b"hello").decode("utf-8"), "docs say bytes are serialized as base64 strings"  # DOC-LITERAL
print("DOCS_OK")
