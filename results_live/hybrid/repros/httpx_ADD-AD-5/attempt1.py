import httpx

response = httpx.Response(200, content=b"hello")
_ = list(response.iter_content())  # DOC-LITERAL
print("DOCS_OK")
