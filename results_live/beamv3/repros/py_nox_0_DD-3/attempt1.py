import inspect
from nox.sessions import Session

default = inspect.signature(Session.run).parameters["external"].default  # DOC-LITERAL
assert default is False, "run() docstring says external defaults to False"  # DOC-LITERAL
print("DOCS_OK")
