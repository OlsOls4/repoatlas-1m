import inspect
import jinja2

param = inspect.signature(jinja2.Environment.install_gettext_callables).parameters["newstyle"]
assert param.default is False, "docs say default newstyle=False"  # DOC-LITERAL
print("DOCS_OK")
