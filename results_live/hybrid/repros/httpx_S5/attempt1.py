import httpx

extensions = {"target": b"*"}
response = httpx.request("CONNECT", "https://www.example.com", extensions=extensions)  # DOC-LITERAL
print("DOCS_OK")
