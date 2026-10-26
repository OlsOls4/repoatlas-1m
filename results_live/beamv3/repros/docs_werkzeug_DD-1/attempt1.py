import warnings
import werkzeug.http as http

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    _ = http.HTTP_STATUS_CODES  # DOC-LITERAL
    assert any("Werkzeug 3.3" in str(w.message) for w in caught), "docs say removed in Werkzeug 3.3"  # DOC-LITERAL

print("DOCS_OK")
