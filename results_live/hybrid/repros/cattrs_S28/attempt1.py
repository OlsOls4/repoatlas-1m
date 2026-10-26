from cattrs import Converter

converter = Converter()
hook = converter.get_structure_hook(int, cache=False)  # DOC-LITERAL
assert callable(hook), "documented call should return a callable hook"

if __name__ == "__main__":
    print("DOCS_OK")
