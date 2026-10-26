import arrow

outputs = {arrow.get(2020, 1, 1, hour).format("H") for hour in range(24)}
assert outputs == {str(hour) for hour in range(25)}, "docs say H produces 0, 1, 2 ... 23, 24"  # DOC-LITERAL
print("DOCS_OK")
