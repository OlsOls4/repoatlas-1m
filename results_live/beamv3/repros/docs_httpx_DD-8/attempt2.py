import httpx

limits = httpx.Limits()  # DOC-LITERAL
assert limits.max_keepalive_connections == 20, "Docs say Defaults 20"  # DOC-LITERAL
assert limits.max_connections == 100, "Docs say Default 100"  # DOC-LITERAL
assert limits.keepalive_expiry == 5, "Docs say Default 5"  # DOC-LITERAL

print("DOCS_OK")
