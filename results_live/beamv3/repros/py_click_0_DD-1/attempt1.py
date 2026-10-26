from click._compat import open_stream

open_stream("output.txt", "w", atomic=True, overwrite=True)  # DOC-LITERAL

print("DOCS_OK")
