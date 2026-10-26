from marshmallow import Schema, fields

class S(Schema):
    value = fields.String(default="DOC_DEFAULT")  # DOC-LITERAL

schema = S()
result = schema.load({})  # DOC-LITERAL
assert result == {"value": "DOC_DEFAULT"}, "docs say a missing value uses its default"  # DOC-LITERAL
print("DOCS_OK")
