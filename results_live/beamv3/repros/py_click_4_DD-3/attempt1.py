import click

bar_with_length = click.progressbar([1, 2, 3])
assert bar_with_length.show_percent is True, "default is True if the iterable has a length"  # DOC-LITERAL

bar_without_length = click.progressbar(iter([1, 2, 3]))
assert bar_without_length.show_percent is False, "default is False if not"  # DOC-LITERAL

print("DOCS_OK")
