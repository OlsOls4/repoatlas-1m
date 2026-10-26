import arrow

assert "'quarter'" in arrow.Arrow.humanize.__doc__, "documentation omits supported granularity 'quarter'"  # DOC-LITERAL
print("DOCS_OK")
