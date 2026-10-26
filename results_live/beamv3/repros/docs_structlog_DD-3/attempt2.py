import structlog
from structlog.testing import CapturingLoggerFactory

RETURN = None

def proc(logger, method, event_dict):
    return RETURN

structlog.configure(processors=[proc], logger_factory=CapturingLoggerFactory())
log = structlog.get_logger()

observed = []
for value in ("x", b"x", bytearray(b"x"), ("a",), {"event": "x"}):
    RETURN = value
    log.info("x")
    observed.append(type(value))

assert set(observed) == {str, bytes, bytearray, tuple}  # DOC-LITERAL
print("DOCS_OK")
