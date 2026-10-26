import sys
from structlog._output import BytesLoggerFactory

factory = BytesLoggerFactory(sys.stdout.buffer)
logger = factory("ignored")  # DOC-LITERAL
assert logger.name is None, "Positional arguments are silently ignored."  # DOC-LITERAL
print("DOCS_OK")
