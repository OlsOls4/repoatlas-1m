import httpx
import inspect
doc = inspect.getdoc(httpx.request) or ""
segment = doc.split('**verify**', 1)[1].split('**trust_env**', 1)[0]  # DOC-LITERAL
assert 'str' in segment, "verify doc omits str (CA bundle path)"  # DOC-LITERAL
print("DOCS_OK")
