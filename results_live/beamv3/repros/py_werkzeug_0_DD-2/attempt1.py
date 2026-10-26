from werkzeug.debug import DebuggedApplication

doc = DebuggedApplication.__doc__ or ""
assert "request_key" in doc, "version note should spell request_key"  # DOC-LITERAL
print("DOCS_OK")
