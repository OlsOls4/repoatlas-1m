import attrs

c1 = lambda value: value
c2 = lambda value: value
c3 = lambda value: value

x = attrs.field(converter=attrs.converter.pipe(c1, c2, c3))  # DOC-LITERAL

print("DOCS_OK")
