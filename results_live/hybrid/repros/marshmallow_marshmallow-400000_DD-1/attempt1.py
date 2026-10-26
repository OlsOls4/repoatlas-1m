from marshmallow import Schema, SchemaOpts, fields


class NamespaceOpts(SchemaOpts):
    def __init__(self, meta, **kwargs):
        SchemaOpts.__init__(self, meta, **kwargs)
        self.name = getattr(meta, "name", None)
        self.plural_name = getattr(meta, "plural_name", self.name)


class NamespacedSchema(Schema):
    OPTIONS_CLASS = NamespaceOpts

    class Meta:
        name = "user"
        plural_name = "users"


class UserSchema(NamespacedSchema):
    name = fields.String()


schema = UserSchema()
assert schema.opts.name == "user", "docs: options name forwarded"  # DOC-LITERAL
assert schema.opts.plural_name == "users", "docs: plural name forwarded"  # DOC-LITERAL
print("DOCS_OK")
