import attrs

@attrs.define
class Point:
    x: int = 0

p = Point()
q = attrs.evolve(p, x=1)  # DOC-LITERAL
assert q.x == 1
assert q is not p
print("DOCS_OK")
