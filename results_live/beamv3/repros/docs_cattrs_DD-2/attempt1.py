import cattrs
import pytest

conv = cattrs.BaseConverter()
with pytest.raises(Exception):
    conv.structure((1, "2"), tuple[int, str])  # DOC-LITERAL
print("DOCS_OK")
