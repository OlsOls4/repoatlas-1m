import arrow

a = arrow.Arrow(2020, 1, 1, 24)  # DOC-LITERAL
assert a.format("HH") == "24", "docs say HH can output 24"  # DOC-LITERAL
print("DOCS_OK")
