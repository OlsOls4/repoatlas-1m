import httpx

limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)  # DOC-LITERAL
client = httpx.Client(limits=limits)  # DOC-LITERAL
assert client.limits == limits, "doc example should apply limits"  # DOC-LITERAL

default_limits = httpx.Client().limits  # DOC-LITERAL
assert default_limits.max_keepalive_connections == 20, "Docs say Defaults 20"  # DOC-LITERAL
assert default_limits.max_connections == 100, "Docs say Default 100"  # DOC-LITERAL
assert default_limits.keepalive_expiry == 5, "Docs say Default 5"  # DOC-LITERAL

print("DOCS_OK")
