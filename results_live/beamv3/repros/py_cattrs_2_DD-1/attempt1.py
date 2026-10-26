import inspect
from cattrs.gen.typeddicts import make_dict_unstructure_fn

sig = inspect.signature(make_dict_unstructure_fn)
assert "_cattrs_detailed_validation" in sig.parameters, "documented parameter is absent"  # DOC-LITERAL
print("DOCS_OK")
