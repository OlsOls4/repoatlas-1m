import nox
from pathlib import Path

Path('pyproject.toml').write_text('''[project]\nclassifiers = [\n  "Programming Language :: Python :: 3.12",\n  "Programming Language :: Python :: 3.13",\n  "Programming Language :: Python :: 3.14",\n  "Programming Language :: Python :: 3.15",\n  "Programming Language :: Python :: Free Threading :: 3 - Stable",\n]\n''')
PYPROJECT = nox.project.load_toml('pyproject.toml')  # DOC-LITERAL
ALL_PYTHON = nox.project.python_versions(PYPROJECT)  # DOC-LITERAL
assert ALL_PYTHON == ['3.12', '3.13', '3.14', '3.14t', '3.15', '3.15t'], 'docs list 3.14t before 3.15'  # DOC-LITERAL
print('DOCS_OK')
