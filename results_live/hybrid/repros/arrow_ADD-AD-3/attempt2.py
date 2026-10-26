import arrow

arrow_obj = arrow.get("2011-02-03")

# DOC-LITERAL-BEGIN
w = arrow_obj.format("W")
# DOC-LITERAL-END
assert w in ("2011-W05-4", "2019-W17"), "docs list 2011-W05-4 and 2019-W17 as W examples"
# sanity: the 2019 example specifically omits weekday
arrow_obj2 = arrow.get("2019-04-24")
w2 = arrow_obj2.format("W")
assert w2 == "2019-W17", "docs example 2019-W17"

print("DOCS_OK")
