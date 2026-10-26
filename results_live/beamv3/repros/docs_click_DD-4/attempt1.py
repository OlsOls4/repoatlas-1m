import click
from click.shell_completion import ShellComplete

_mysh_source = """\
%(complete_func)s {
    response=$(%(complete_var)s=mysh_complete %(foo_bar)s)
}
"""

class MyShellComplete(ShellComplete):
    source_template = _mysh_source

complete = MyShellComplete(click.Command("foo"), {}, "foo", "_FOO_COMPLETE")  # DOC-LITERAL
script = complete.source()  # DOC-LITERAL
print("DOCS_OK")
