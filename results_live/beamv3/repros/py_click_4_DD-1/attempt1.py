import click
value = click.style(message=42)  # DOC-LITERAL
assert isinstance(value, str), "style returns a string"
print("DOCS_OK")
