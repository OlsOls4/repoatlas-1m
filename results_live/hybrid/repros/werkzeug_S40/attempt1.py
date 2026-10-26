import werkzeug.middleware

cls = werkzeug.middleware.SharedDataMiddleware  # DOC-LITERAL
assert cls.__name__ == "SharedDataMiddleware"
print("DOCS_OK")
