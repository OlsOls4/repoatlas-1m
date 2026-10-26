import click

# DOC-LITERAL-BEGIN
file_type_class = click.FileType
# DOC-LITERAL-END
assert file_type_class is click.File, "docs name the file parameter type as FileType"
print("DOCS_OK")
