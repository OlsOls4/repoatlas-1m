import attr._make

args = {"cmp": True}
cls = attr._make.make_class("C", ["x"], attributes_arguments=args)
assert args == {"cmp": True}, "attributes_arguments passed unmodified to attr.s"
print("DOCS_OK")
