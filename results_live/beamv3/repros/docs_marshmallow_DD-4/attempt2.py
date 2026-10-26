from marshmallow import Schema, fields

class S(Schema):
    value = fields.String()

# Docs refer to the field's default value.
S.value.default = "DOC_DEFAULT"

result = S().load({})  # DOC-LITERAL
assert result == {"value": "DOC_DEFAULT"}, "docs say a missing value uses its default"  # DOC-LITERAL
print("DOCS_OK")
