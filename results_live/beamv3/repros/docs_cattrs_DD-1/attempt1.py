import cattrs
import typing

converter = cattrs.Converter()
data = [1, 2, 3]
structured = converter.structure(data, typing.Sequence[int])  # DOC-LITERAL
assert isinstance(structured, list), "typing.Sequence[T] converts to lists"  # DOC-LITERAL
assert structured == [1, 2, 3], "typing.Sequence[T] converts to lists"  # DOC-LITERAL
print("DOCS_OK")
