import arrow

dt = arrow.get("2020-12-31")
value = dt.format("DDD")
assert int(value) <= 365, "documented DDD range is 1..365"  # DOC-LITERAL
print("DOCS_OK")
