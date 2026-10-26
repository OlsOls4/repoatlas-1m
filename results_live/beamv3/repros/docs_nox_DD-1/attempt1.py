import json
import os
import subprocess
import sys
import tempfile

td = tempfile.mkdtemp()
with open(os.path.join(td, "noxfile.py"), "w") as f:
    f.write("import nox\n\n@nox.session\ndef tests(session):\n    pass\n")

proc = subprocess.run(
    [sys.executable, "-m", "nox", "--json"],
    cwd=td,
    capture_output=True,
    text=True,
)
json.loads(proc.stdout)  # DOC-LITERAL
print("DOCS_OK")
