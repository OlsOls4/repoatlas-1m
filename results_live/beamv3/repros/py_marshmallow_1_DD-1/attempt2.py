from marshmallow.schema import SchemaOpts

meta = type("Meta", (), {"additional": ["foo"]})
opts = SchemaOpts(meta)
assert opts.additional == ["foo"], "SchemaOpts should expose the documented additional option"  # DOC-LITERAL
print("DOCS_OK")
