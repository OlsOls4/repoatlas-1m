import arrow

result = arrow.fromordinal(737741)  # DOC-LITERAL
assert repr(result) == "<Arrow [2020-11-12T00:00:00+00:00]>", "documented fromordinal output"
print("DOCS_OK")
