import werkzeug

# DOC-LITERAL-BEGIN
orig = werkzeug.proxy_fix.orig
# DOC-LITERAL-END
assert isinstance(orig, dict), "environ as werkzeug.proxy_fix.orig, a dict."
print("DOCS_OK")
