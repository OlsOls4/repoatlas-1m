import werkzeug

value = werkzeug.proxy_fix.orig  # DOC-LITERAL
assert isinstance(value, dict), "docs say values are stored in this dict"
print("DOCS_OK")
