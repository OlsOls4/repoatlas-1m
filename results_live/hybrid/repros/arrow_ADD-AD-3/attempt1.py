import arrow

# A date in ISO week 17 of 2019 (depth-first doc example 2019-W17).
arrow_obj = arrow.get("2019-04-24")

# DOC-LITERAL
w = arrow_obj.format("W")
assert w == "2019-W17", "docs example for W claims 2019-W17"

print("DOCS_OK")
