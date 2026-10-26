import attr._make

args = {"cmp": True}
cls = attr._make.make_class("C", ["x"], attributes_arguments=args)  # DOC-LITERAL
assert args == {"cmp": True}, "attributes_arguments passed unmodified to attr.s"  # DOC-LITERAL
print("DOCS_OK")
