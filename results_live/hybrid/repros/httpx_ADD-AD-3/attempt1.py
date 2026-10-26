import httpx

url = httpx.URL("https://example.com")
assert isinstance(url.is_ssl, bool)  # DOC-LITERAL
print("DOCS_OK")
