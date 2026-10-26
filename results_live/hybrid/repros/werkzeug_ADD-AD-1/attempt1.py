from werkzeug.wrappers import Request

doc = Request.input_stream.__doc__ or ""
bad_phrase = 'Use ``environ["REMOTE_USER"]`` instead.'
assert bad_phrase not in doc, "deprecated input_stream should point to stream, not REMOTE_USER"  # DOC-LITERAL
print("DOCS_OK")
