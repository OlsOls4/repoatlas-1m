from marshmallow import Schema, fields
from marshmallow.decorators import pre_load

class UserSchema(Schema):
    name = fields.String()

    @pre_load(pass_many=True)  # DOC-LITERAL
    def preprocess(self, data, many=False):
        return data

print("DOCS_OK")
