import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    (Path(td) / 'noxfile.py').write_text(
        'import nox\n\n'
        '@nox.session\n'
        'def tests(session):\n'
        '    """Run the test suite."""\n'
        "    session.run('pytest')\n"
    )
    result = subprocess.run(
        ['nox', '--list'],
        cwd=td,
        capture_output=True,
        text=True,
    )
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    assert result.returncode == 0
    assert 'Available sessions:' in result.stdout  # DOC-LITERAL

print('DOCS_OK')
