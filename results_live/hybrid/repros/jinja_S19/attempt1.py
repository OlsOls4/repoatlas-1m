from jinja2 import Environment
from jinja2.runtime import LoopContext

environment = Environment()
loop = LoopContext([1, 2, 3], environment.undefined)
loop._peek_next()
loop._last  # DOC-LITERAL
print("DOCS_OK")
