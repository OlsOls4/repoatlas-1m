import subprocess
import tempfile
import tomllib
from pathlib import Path

tmp = tempfile.mkdtemp()
result = subprocess.run(["poetry", "new", "poetry-demo"], cwd=tmp, capture_output=True, text=True)
assert result.returncode == 0, result.stderr
pyproject = Path(tmp) / "poetry-demo" / "pyproject.toml"
data = tomllib.loads(pyproject.read_text())
assert data["project"]["requires-python"] == ">=3.9"  # DOC-LITERAL
print("DOCS_OK")
