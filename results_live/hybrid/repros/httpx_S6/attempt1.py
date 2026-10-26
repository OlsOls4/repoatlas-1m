import httpx

# DOC-LITERAL-BEGIN
mounts = httpx.Mounts({"http://": httpx.BaseTransport})
# DOC-LITERAL-END

print("DOCS_OK")
