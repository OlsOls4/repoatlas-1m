import inspect
import jinja2

env = jinja2.Environment(extensions=["jinja2.ext.i18n"])
param = inspect.signature(env.install_gettext_callables).parameters["newstyle"]  # DOC-LITERAL
assert param.default is False, "docs say default newstyle=False"  # DOC-LITERAL
print("DOCS_OK")
