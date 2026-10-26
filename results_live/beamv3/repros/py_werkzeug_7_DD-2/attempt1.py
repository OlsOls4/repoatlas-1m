from werkzeug.sansio.request import Request

request = Request.from_values()
assert request.user_agent is None, "docs say user_agent is None if not set"  # DOC-LITERAL
print("DOCS_OK")
