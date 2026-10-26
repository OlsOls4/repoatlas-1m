from nox._parametrize import Param

# The docstring documents a parameter named `args`, so use it literally as a keyword.
p = Param(args=[1, 2])  # DOC-LITERAL
assert p.args == [1, 2], "Param(args=...) should populate args as documented"
print("DOCS_OK")
