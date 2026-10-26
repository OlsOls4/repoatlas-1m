from cattrs import Converter

converter = Converter()
hook = converter.get_unstructure_hook(int, cache=False)  # DOC-LITERAL
assert callable(hook), "documented call should return a hook"
print("DOCS_OK")
