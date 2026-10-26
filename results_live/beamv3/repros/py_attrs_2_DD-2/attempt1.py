import attrs

A = attrs.make_class("A", ["x", "y"])  # DOC-LITERAL
assert A.__name__ == "A"
a = A(1, 2)
assert (a.x, a.y) == (1, 2)

B = attrs.make_class("B", {"x": attrs.field(default=1), "y": attrs.field(default=2)})  # DOC-LITERAL
assert B.__name__ == "B"
b = B()
assert (b.x, b.y) == (1, 2)

print("DOCS_OK")
