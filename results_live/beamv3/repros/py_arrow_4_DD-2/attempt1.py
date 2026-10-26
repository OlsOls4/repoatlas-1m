import inspect
import arrow

sig = inspect.signature(arrow.Arrow.dehumanize)
assert sig.parameters["locale"].default == "en-us", "documentation says default locale is 'en-us'"  # DOC-LITERAL
print("DOCS_OK")
