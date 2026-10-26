from pathlib import Path

from click.testing import CliRunner

from nox.__main__ import main

runner = CliRunner()
with runner.isolated_filesystem():
    Path('noxfile.py').write_text(
        'import nox\n\n'
        '@nox.session\n'
        'def tests(session):\n'
        '    """Run the test suite."""\n'
        "    session.run('pytest')\n"
    )
    result = runner.invoke(main, ['--list'])  # DOC-LITERAL
    print(result.output, end='')
    assert result.exit_code == 0
    assert 'Available sessions:' in result.output  # DOC-LITERAL

print('DOCS_OK')
