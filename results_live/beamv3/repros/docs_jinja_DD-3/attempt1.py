import inspect
import jinja2

env = jinja2.Environment(extensions=["jinja2.ext.i18n"])
env.install_null_translations()  # DOC-LITERAL
assert env.newstyle_gettext is False, "install_null_translations() should make newstyle False"
sig = inspect.signature(env.install_null_translations)
assert sig.parameters["newstyle"].default is False, "documented default is newstyle=False"  # DOC-LITERAL
print("DOCS_OK")
