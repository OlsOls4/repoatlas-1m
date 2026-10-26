import inspect

from pydantic_settings import BaseSettings

assert inspect.signature(BaseSettings.__init__).parameters['cli_kebab_case'].default is True, "docs say cli_kebab_case defaults to True"  # DOC-LITERAL
print('DOCS_OK')
