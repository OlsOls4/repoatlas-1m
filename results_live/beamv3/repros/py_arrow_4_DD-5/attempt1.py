import arrow
from datetime import datetime

start = datetime(2020, 1, 1)
spans = list(arrow.Arrow.span_range("day", start, limit=3))  # DOC-LITERAL
assert len(spans) == 3, "span_range should return 3 spans"
print("DOCS_OK")
