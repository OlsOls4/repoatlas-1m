from jinja2 import Environment
from jinja2.parser import Parser

env = Environment()
parser = Parser(env, "a, b")
parser.parse_tuple(no_condexpr=True)  # DOC-LITERAL
print("DOCS_OK")
