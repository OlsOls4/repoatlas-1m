import click

with click.progressbar([1, 2, 3]) as bar_with_length:
    assert bar_with_length.show_percent is True, "default is True if the iterable has a length"  # DOC-LITERAL

with click.progressbar(iter([1, 2, 3])) as bar_without_length:
    assert bar_without_length.show_percent is False, "default is False if not"  # DOC-LITERAL

print("DOCS_OK")
