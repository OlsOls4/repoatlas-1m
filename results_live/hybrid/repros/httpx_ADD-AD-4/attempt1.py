import httpx

# DOC-LITERAL-BEGIN
snippet = 'mounts={"all://": ..., httpx.HTTPTransport(proxy="all://www.example.com": None})'
compile(snippet, "docs/compatibility.md:168", "exec")
# DOC-LITERAL-END

print("DOCS_OK")
