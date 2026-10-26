import attrs
import attrs.validators as V

@attrs.define
class Foo:
    x = attrs.field(validator=V.not_(V.in_([1]), exc_types=(ValueError,)))  # DOC-LITERAL

f = Foo(2)
assert f.x == 2, "documented tuple form should be accepted"
print("DOCS_OK")
