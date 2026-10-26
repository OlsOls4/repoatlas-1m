import io
import click

out = io.StringIO()
with click.progressbar(range(2), label="TestLabel", hidden=False, file=out) as bar:  # DOC-LITERAL
    for _ in bar:
        pass
assert "TestLabel" not in out.getvalue(), "docs: hidden=False disables label"  # DOC-LITERAL
print("DOCS_OK")
