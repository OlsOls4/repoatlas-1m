from arrow import locales

loc = locales.get_locale("si")
negative = loc.describe("second", -5, only_distance=False)
positive = loc.describe("second", 5, only_distance=False)
assert negative == positive, "key is always future when only_distance=False"  # DOC-LITERAL
print("DOCS_OK")
