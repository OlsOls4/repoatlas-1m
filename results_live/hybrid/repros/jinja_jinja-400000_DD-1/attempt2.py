from jinja2 import Environment
env = Environment(extensions=['jinja2.ext.i18n'])
env.newstyle_gettext = True
env.install_null_translations()  # DOC-LITERAL
assert env.newstyle_gettext is False, "docs say default newstyle=False forces false"  # DOC-LITERAL
print('DOCS_OK')
