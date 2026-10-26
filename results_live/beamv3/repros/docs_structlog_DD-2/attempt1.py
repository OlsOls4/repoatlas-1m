import sys
sys.modules['rich'] = None
import better_exceptions  # noqa: F401
import structlog.dev
assert structlog.dev.default_exception_formatter is structlog.dev.plain_traceback, "docs say plain_traceback is default if Rich is not installed"  # DOC-LITERAL
print("DOCS_OK")
