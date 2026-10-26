from marshmallow import Schema, fields, pre_load

class EnvelopeSchema(Schema):
    name = fields.String()

    @pre_load(pass_many=True)  # DOC-LITERAL
    def unwrap_envelope(self, data, many, **kwargs):
        return data

print("DOCS_OK")
