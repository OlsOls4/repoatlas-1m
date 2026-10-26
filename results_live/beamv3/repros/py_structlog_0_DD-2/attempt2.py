import inspect
import structlog.typing

cls = structlog.typing.FilteringBoundLogger
sig = inspect.signature(cls.new)
actual_param = next(p.name for p in sig.parameters.values() if p.kind is inspect.Parameter.VAR_KEYWORD)
documented_param = "initial_values"  # DOC-LITERAL
assert documented_param == actual_param, f"docs say {documented_param}, signature uses {actual_param}"
print("DOCS_OK")
