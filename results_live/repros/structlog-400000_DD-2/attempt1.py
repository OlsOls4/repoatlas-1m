import structlog.stdlib

mapping = structlog.stdlib._log_levels._NAME_TO_LEVEL  # DOC-LITERAL
assert isinstance(mapping, dict), "documented mapping of names to numbers"
print("DOCS_OK")
