import inspect
from marshmallow import Schema

doc = inspect.getdoc(Schema.loads)
assert ":param many: Whether to deserialize `s` as a collection." in doc, "loads doc refers to nonexistent obj"  # DOC-LITERAL
print("DOCS_OK")
