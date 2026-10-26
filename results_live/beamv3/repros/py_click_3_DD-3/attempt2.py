import click
from click.shell_completion import _resolve_context


@click.command()
def cli() -> None:
    pass


_resolve_context(cli=cli, prog_name="prog", args=[])  # DOC-LITERAL
print("DOCS_OK")
