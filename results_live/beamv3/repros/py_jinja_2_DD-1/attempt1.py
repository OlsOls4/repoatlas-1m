from jinja2 import Environment
from jinja2.compiler import generate

env = Environment()
node = env.parse("{% if False %}{% endif %}")
source = generate(node, env, "test", "test.jinja")
assert "if 0: yield None" in source  # DOC-LITERAL
print("DOCS_OK")
