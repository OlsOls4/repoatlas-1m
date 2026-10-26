from marshmallow import Schema, fields, post_dump


class BadSchema(Schema):
    name = fields.Str()

    @post_dump(pass_many=True)  # DOC-LITERAL
    def wrap_with_envelope(self, data, many, **kwargs):
        return {"key": data}


print("DOCS_OK")
