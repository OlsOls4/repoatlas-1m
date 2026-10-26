from cattrs.preconf.cbor2 import make_converter

converter = make_converter()
s = {1, 2, 3}
u = converter.unstructure(s)  # DOC-LITERAL
assert isinstance(u, set), "Sets are serialized and deserialized to sets."  # DOC-LITERAL
r = converter.structure(u, set)
assert r == s, "Sets are serialized and deserialized to sets."  # DOC-LITERAL
print("DOCS_OK")
