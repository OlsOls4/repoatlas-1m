import json
from jinja2 import Environment
from jinja2.utils import htmlsafe_json_dumps

env = Environment()
def custom_dumps(obj):
    return '{"custom": true}'
env.policies["json.dumps_function"] = custom_dumps

result = htmlsafe_json_dumps({"a": 1})  # DOC-LITERAL
assert '"custom"' in result, "docs say dumps defaults to env.policies[json.dumps_function]"  # DOC-LITERAL
print("DOCS_OK")
