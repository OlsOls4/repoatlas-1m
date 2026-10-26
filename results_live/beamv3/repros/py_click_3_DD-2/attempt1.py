from click import Option
from click.shell_completion import _is_incomplete_option

_is_incomplete_option([], Option(["--foo"]))  # DOC-LITERAL
