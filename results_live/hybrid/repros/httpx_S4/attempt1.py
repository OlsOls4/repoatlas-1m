import httpx

extensions = {"target": b"/test^path"}
response = httpx.get("https://www.example.com", extensions=extensions)  # DOC-LITERAL
print("DOCS_OK")
