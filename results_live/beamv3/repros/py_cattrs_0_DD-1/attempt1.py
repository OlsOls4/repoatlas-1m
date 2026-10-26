import inspect
import cattrs.gen

# DOC-LITERAL-BEGIN
doc = inspect.getdoc(cattrs.gen.make_dict_structure_fn_from_attrs)
# DOC-LITERAL-END
assert "structuring." in doc, "docs should say structuring."
print("DOCS_OK")
