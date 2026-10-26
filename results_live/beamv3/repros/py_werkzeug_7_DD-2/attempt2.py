from werkzeug.test import create_environ
from werkzeug.sansio.request import Request

request = Request(create_environ())
assert request.user_agent is None, "docs say user_agent is None if not set"  # DOC-LITERAL
print("DOCS_OK")
