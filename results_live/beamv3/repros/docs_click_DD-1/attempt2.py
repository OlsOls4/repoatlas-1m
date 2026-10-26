import click
from click.testing import CliRunner

@click.command()
@click.option('--message', '-m', multiple=True, default='abc')  # DOC-LITERAL
def commit(message):
    click.echo(message)

runner = CliRunner()
result = runner.invoke(commit, catch_exceptions=False)  # DOC-LITERAL
assert result.output == "('a', 'b', 'c')\n"  # DOC-LITERAL
print('DOCS_OK')
