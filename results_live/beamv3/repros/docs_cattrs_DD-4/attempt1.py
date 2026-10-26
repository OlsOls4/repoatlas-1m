from datetime import datetime, timezone

from cattrs.preconf.cbor2 import make_converter

converter = make_converter()
dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
unstructured = converter.unstructure(dt)
assert isinstance(unstructured, str), "docs say datetimes are serialized as a text string by default"  # DOC-LITERAL
print("DOCS_OK")
