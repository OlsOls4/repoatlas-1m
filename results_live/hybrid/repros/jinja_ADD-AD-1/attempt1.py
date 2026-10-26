from jinja2 import Environment

env = Environment(extensions=["jinja2.ext.i18n"])
env.install_translations(newstyle=True)  # DOC-LITERAL
print("DOCS_OK")
