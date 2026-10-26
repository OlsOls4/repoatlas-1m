import gettext
import jinja2

env = jinja2.Environment(extensions=["jinja2.ext.i18n"])
env.newstyle_gettext = True
translations = gettext.NullTranslations()
env.install_gettext_translations(translations)  # DOC-LITERAL
assert env.newstyle_gettext is False, "docs default newstyle=False"
print("DOCS_OK")
