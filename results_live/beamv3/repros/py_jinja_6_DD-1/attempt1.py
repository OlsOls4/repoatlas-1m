from jinja2.tests import test_sequence, test_iterable

value = [1, 2, 3]
assert test_sequence(value) is True  # DOC-LITERAL
assert test_iterable(value)  # DOC-LITERAL
print("DOCS_OK")
