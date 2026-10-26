from werkzeug.exceptions import RequestRedirect  # DOC-LITERAL

# If the docs (cross-ref werkzeug.exceptions.RequestRedirect) are right, this succeeds.
assert RequestRedirect is not None  # DOC-LITERAL
print("DOCS_OK")
