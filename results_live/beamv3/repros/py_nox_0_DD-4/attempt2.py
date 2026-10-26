import inspect
import nox

param = inspect.signature(nox.Session.run).parameters["external"]
annotation = param.annotation
if isinstance(annotation, str):
    assert annotation == "bool", "documentation says external type is bool"  # DOC-LITERAL
else:
    assert annotation is bool, "documentation says external type is bool"  # DOC-LITERAL
print("DOCS_OK")
