import json
import os
import sys
import tempfile

td = tempfile.mkdtemp()
with open(os.path.join(td, "noxfile.py"), "w") as f:
    f.write("import nox\n\n@nox.session\ndef tests(session):\n    pass\n")

out = os.path.join(td, "output.json")
os.chdir(td)
os.system(f"{sys.executable} -m nox --json > {out} 2> {os.path.join(td, 'stderr.txt')}")

with open(out) as f:
    json.load(f)  # DOC-LITERAL
print("DOCS_OK")
