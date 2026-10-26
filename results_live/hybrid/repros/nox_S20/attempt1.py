import nox.sessions

session = nox.sessions.Session.__new__(nox.sessions.Session)
session.conda_install("pytest", channels=["conda-forge"])  # DOC-LITERAL
print("DOCS_OK")
