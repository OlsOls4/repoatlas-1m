import click


@click.command()
def cli() -> None:
    pass


click.shell_completion._resolve_context(cli=cli, prog_name="prog", args=[])  # DOC-LITERAL
print("DOCS_OK")
