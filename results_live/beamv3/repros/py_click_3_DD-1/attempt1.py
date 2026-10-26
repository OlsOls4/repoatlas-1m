from click.shell_completion import ShellComplete

doc = ShellComplete.__doc__ or ""
assert ":param ctx_args:" in doc, "ShellComplete docstring omits ctx_args accepted by __init__"  # DOC-LITERAL

print("DOCS_OK")
