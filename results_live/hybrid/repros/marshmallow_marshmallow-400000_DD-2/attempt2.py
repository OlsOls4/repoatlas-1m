from marshmallow import Schema, fields

class S(Schema):
    x = fields.String(default="DEFAULT", load_default="LOAD_DEFAULT")

data = S().load({})
assert data["x"] == "DEFAULT", "docs say default value is used"  # DOC-LITERAL
print("DOCS_OK")
