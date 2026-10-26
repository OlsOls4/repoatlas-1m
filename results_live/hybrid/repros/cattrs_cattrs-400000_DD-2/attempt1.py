from cattrs import Converter

conv = Converter()
hook = conv.get_unstructure_hook(int, cache=True)  # DOC-LITERAL
print("DOCS_OK")
