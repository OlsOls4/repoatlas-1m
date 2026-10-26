import linecache
from typing import TypedDict
from cattrs import Converter
from cattrs.gen.typeddicts import make_dict_structure_fn

class TD(TypedDict):
    x: int

conv = Converter()
fn = make_dict_structure_fn(TD, conv, _cattrs_detailed_validation=False)  # DOC-LITERAL
assert not linecache.getlines(fn.__code__.co_filename), "_cattrs_detailed_validation should control linecache storage"  # DOC-LITERAL
print("DOCS_OK")
