import attrs
from nox import _options

field = attrs.fields(_options.Options)["download_python"]
meta = field.metadata
if isinstance(meta.get("nox"), dict):
    meta = meta["nox"]
help_text = meta["help"]
assert "defaults to 'auto'" in help_text, "help text should state the default is 'auto'"  # DOC-LITERAL
print("DOCS_OK")
