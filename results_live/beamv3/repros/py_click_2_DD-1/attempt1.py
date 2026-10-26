import os
import click
from click.testing import CliRunner

os.environ['MYFLAG'] = '0'

captured = []

@click.command()
@click.option('--foo', flag_value='special', envvar='MYFLAG')
def cmd(foo):
    captured.append(foo)

runner = CliRunner()
runner.invoke(cmd, [])
assert captured and captured[0] == 'special', 'envvar used with flag_value will always use the flag_value'  # DOC-LITERAL
print('DOCS_OK')
