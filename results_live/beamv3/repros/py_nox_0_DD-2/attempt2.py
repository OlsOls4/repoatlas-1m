import subprocess
import sys

# DOC-LITERAL-BEGIN
completed = subprocess.run(
    [sys.executable, "-m", "nox", "--help"],
    check=True,
    capture_output=True,
    text=True,
)
assert "Default is 1 (sequential)." in completed.stdout  # DOC-LITERAL
# DOC-LITERAL-END
print("DOCS_OK")
