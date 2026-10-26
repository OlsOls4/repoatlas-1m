from datetime import datetime
import arrow

intervals = list(arrow.Arrow.interval("day", datetime(2020, 1, 1)))  # DOC-LITERAL
print("DOCS_OK")
