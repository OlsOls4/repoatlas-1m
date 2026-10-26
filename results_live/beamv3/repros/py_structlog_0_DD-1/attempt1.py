import structlog

logger = structlog.get_logger()  # DOC-LITERAL
bound = logger.bind()
assert type(bound) is structlog.BoundLogger, "default bound logger is structlog.BoundLogger by default."  # DOC-LITERAL
print("DOCS_OK")
