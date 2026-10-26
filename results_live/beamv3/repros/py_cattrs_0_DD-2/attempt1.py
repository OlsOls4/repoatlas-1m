from cattrs.gen import make_dict_structure_fn

# DOC-LITERAL-BEGIN
doc = make_dict_structure_fn.__doc__
assert "structuring." in doc, "make_dict_structure_fn docs should mention structuring"
assert "unstructuring." not in doc, "make_dict_structure_fn docs incorrectly mention unstructuring"
# DOC-LITERAL-END

print("DOCS_OK")
