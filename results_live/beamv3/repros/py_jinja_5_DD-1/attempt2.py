from jinja2.sandbox import is_internal_attribute

def documented_function():
    pass

assert is_internal_attribute(str, "mro") is True  # DOC-LITERAL
assert is_internal_attribute(str, "upper") is False  # DOC-LITERAL
assert is_internal_attribute(documented_function, "func_code") is True  # DOC-LITERAL
print("DOCS_OK")
