from werkzeug.middleware.shared_data import SharedDataMiddleware

app = lambda environ, start_response: None
middleware = SharedDataMiddleware(app, {})
assert middleware.fallback_mimetype == "application/octet-stream", "default fallback_mimetype is application/octet-stream"  # DOC-LITERAL
print("DOCS_OK")
