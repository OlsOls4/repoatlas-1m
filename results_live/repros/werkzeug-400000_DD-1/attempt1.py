from werkzeug.http import dump_cookie

cookie = dump_cookie("key")  # DOC-LITERAL
assert "Path=" not in cookie, "docs say path defaults to None"  # DOC-LITERAL
print("DOCS_OK")
