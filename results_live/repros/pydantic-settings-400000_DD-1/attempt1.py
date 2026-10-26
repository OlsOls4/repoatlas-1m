from pydantic_settings import BaseSettings

assert BaseSettings.model_config.get("cli_kebab_case") is True, "docs say cli_kebab_case defaults to True"  # DOC-LITERAL
print("DOCS_OK")
