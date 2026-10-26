import os
import tempfile
import tomllib
from pathlib import Path
from cleo.testers.command_tester import CommandTester
from poetry.console.application import Application

with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    app = Application()
    tester = CommandTester(app.find("init"))
    status = tester.execute("--name poetry-demo --no-interaction")
    assert status == 0, tester.get_display()
    data = tomllib.loads((Path(d) / "pyproject.toml").read_text())
    assert data["project"]["requires-python"] == ">=3.9"  # DOC-LITERAL
print("DOCS_OK")
