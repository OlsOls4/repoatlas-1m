import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "nox", "--help"],
    capture_output=True,
    text=True,
)
help_text = result.stdout + result.stderr
assert "defaults to 'auto'" in help_text, "help text should state the default is 'auto'"  # DOC-LITERAL
print("DOCS_OK")
