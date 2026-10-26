import datetime
from werkzeug.http import dump_cookie

cookie_dt = dump_cookie("k", expires=datetime.datetime(2030, 1, 1))  # DOC-LITERAL
assert isinstance(cookie_dt, str)
assert "Expires=" in cookie_dt

cookie_int = dump_cookie("k", expires=1700000000)  # DOC-LITERAL
assert isinstance(cookie_int, str)
assert "Expires=" in cookie_int

print("DOCS_OK")
