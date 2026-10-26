import cattrs
from attrs import define
from cattrs.errors import ForbiddenExtraKeyError  # DOC-LITERAL

@define
class TestClass:
    number: int = 1

c = cattrs.Converter(forbid_extra_keys=True)  # DOC-LITERAL
c.structure({"nummber": 2}, TestClass)  # DOC-LITERAL
