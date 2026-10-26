import argparse
import inspect
from pydantic_settings import BaseSettings
from pydantic_settings.sources.providers.cli import CliSettingsSource

sig = inspect.signature(CliSettingsSource.__init__)
assert sig.parameters['parse_args_method'].default is argparse.ArgumentParser.parse_args, "parse_args_method defaults to argparse.ArgumentParser.parse_args"  # DOC-LITERAL
print("DOCS_OK")
