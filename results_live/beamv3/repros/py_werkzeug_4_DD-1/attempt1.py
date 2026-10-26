import inspect
from werkzeug.datastructures.auth import WWWAuthenticate

doc = inspect.getdoc(WWWAuthenticate.token.fget)
assert doc == "A token for the header. Only one of this or :attr:`parameters` should\nhave a value for a given scheme."  # DOC-LITERAL
print("DOCS_OK")
