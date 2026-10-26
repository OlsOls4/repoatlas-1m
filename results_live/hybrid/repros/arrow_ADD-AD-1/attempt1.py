import arrow

dt = arrow.get("2020-12-31")
formatted = dt.format("DDDD")  # DOC-LITERAL
assert 1 <= int(formatted) <= 365, f"docs say DDDD outputs 001..365, got {formatted}"  # DOC-LITERAL
print("DOCS_OK")
