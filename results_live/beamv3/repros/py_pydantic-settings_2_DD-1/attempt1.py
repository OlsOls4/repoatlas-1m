from pydantic_settings import BaseSettings
from pydantic_settings.sources.providers.cli import CliSettingsSource

class Settings(BaseSettings):
    value: int = 1

source = CliSettingsSource(Settings, cli_parse_args=None)  # DOC-LITERAL
assert source.cli_prog_name is None, "cli_prog_name defaults to None when cli_parse_args is None"  # DOC-LITERAL
print("DOCS_OK")
