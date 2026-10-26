import click
from click.testing import CliRunner

@click.command()
@click.option("--flag/--no-flag", envvar="FLAG", default=False)
def cmd(flag):
    click.echo(f"RESULT={flag}")

runner = CliRunner()
result = runner.invoke(cmd, [], env={"FLAG": "definitely-not-a-bool"})  # DOC-LITERAL
assert result.exit_code == 0, result.output  # DOC-LITERAL
assert "RESULT=False" in result.output, result.output  # DOC-LITERAL
print("DOCS_OK")
