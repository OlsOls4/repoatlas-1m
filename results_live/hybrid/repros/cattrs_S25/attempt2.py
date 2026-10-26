from attrs import define
import cattrs
from cattrs.gen import make_dict_structure_fn

@define
class TestClass:
    number: int = 1

# DOC-LITERAL-BEGIN
c = cattrs.Converter(forbid_extra_keys=True)
c.structure({"nummber": 2}, TestClass)
# DOC-LITERAL-END
