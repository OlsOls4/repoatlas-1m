from arrow.parser import TzinfoParser
import datetime

assert ":rtype: datetime.timezone" in (TzinfoParser.parse.__doc__ or "")  # DOC-LITERAL
assert TzinfoParser.parse.__annotations__.get("return") is datetime.timezone  # DOC-LITERAL

print("DOCS_OK")
