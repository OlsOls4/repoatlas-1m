from werkzeug.sansio.response import Response

doc = Response.access_control_expose_headers.__doc__
assert doc is not None
assert doc.lstrip().startswith("The ``Access-Control-Expose-Headers`` header.")  # DOC-LITERAL
print("DOCS_OK")
