import attrs
import attrs.validators as V

@attrs.define
class Foo:
    x = attrs.field(validator=V.not_(V.in_([1]), exc_types=(ValueError,)))  # DOC-LITERAL

f = Foo(2)  # inner raises ValueError, not_ passes
assert f.x == 2, "value 2 should be accepted"
try:
    Foo(1)
except ValueError:
    pass
else:
    raise AssertionError("value 1 should be rejected")
print("DOCS_OK")
