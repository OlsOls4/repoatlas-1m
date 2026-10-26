import inspect
from starlette.requests import Request

sig = inspect.signature(Request.__init__)
params = sig.parameters

# DOC-LITERAL-BEGIN
assert params["receive"].default is inspect.Parameter.empty, "docs say receive is required"  # DOC-LITERAL
assert params["send"].default is inspect.Parameter.empty, "docs say send is required"  # DOC-LITERAL
# DOC-LITERAL-END

print("DOCS_OK")
