import structlog
from structlog import make_filtering_bound_logger
from structlog._log_levels import NAME_TO_LEVEL

make_filtering_bound_logger("info")  # DOC-LITERAL
documented_keys = {"critical", "error", "warning", "info", "debug", "notset"}
assert set(NAME_TO_LEVEL) == documented_keys, "docs say min_level string must be one of documented keys"  # DOC-LITERAL
print("DOCS_OK")
