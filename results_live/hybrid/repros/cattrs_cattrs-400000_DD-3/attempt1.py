from cattrs import Converter

converter = Converter()

# The docstring names the option `cache`, so use it as a keyword.
converter.get_structure_hook(int, cache=False)  # DOC-LITERAL

print("DOCS_OK")
