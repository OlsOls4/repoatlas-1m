from werkzeug.datastructures import Headers
h = Headers()
h.setlist(key="X", value=["a", "b"])  # DOC-LITERAL
assert h.getlist("X") == ["a", "b"], "header values not set as documented"
print("DOCS_OK")
