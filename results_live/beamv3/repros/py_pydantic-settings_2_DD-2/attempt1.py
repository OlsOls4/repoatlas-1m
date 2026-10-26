import argparse
import inspect
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from pydantic_settings.sources.providers.cli import CliSettingsSource


class Settings(BaseSettings):
    pass


src = CliSettingsSource(Settings)
assert src.parse_args_method is argparse.ArgumentParser.parse_args, "parse_args_method should default to argparse.ArgumentParser.parse_args"  # DOC-LITERAL
print("DOCS_OK")
