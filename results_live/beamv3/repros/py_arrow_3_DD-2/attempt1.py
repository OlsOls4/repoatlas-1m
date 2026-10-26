import arrow.locales as locales

candidates = [
    getattr(locales, name)
    for name in dir(locales)
    if name.endswith("Locale") and hasattr(getattr(locales, name), "timeframes_only_distance")
]
assert candidates
candidate = candidates[0]
locale = candidate()
# DOC-LITERAL-BEGIN
result_past = locale.describe("seconds", -5)
result_future = locale.describe("seconds", 5)
assert result_past == result_future, "key is always future when only_distance=False"
# DOC-LITERAL-END
print("DOCS_OK")
