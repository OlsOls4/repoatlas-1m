import inspect
import arrow

sig = inspect.signature(arrow.Arrow.dehumanize)
assert sig.parameters["locale"].default == "en-us", "doc says locale defaults to 'en-us'"  # DOC-LITERAL
print("DOCS_OK")
