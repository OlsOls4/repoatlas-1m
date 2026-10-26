import structlog
from structlog.testing import CapturingLoggerFactory

RETURN = None

def proc(logger, method, event_dict):
    return RETURN

structlog.configure(processors=[proc], logger_factory=CapturingLoggerFactory())
log = structlog.get_logger()
accepted_types = []
for value in ("x", b"x", bytearray(b"x"), ("x",), {"event": "x"}):
    RETURN = value
    try:
        log.info("x")
        accepted_types.append(type(value))
    except Exception:
        pass
assert set(accepted_types) == {str, bytes, bytearray, tuple}  # DOC-LITERAL
print("DOCS_OK")
