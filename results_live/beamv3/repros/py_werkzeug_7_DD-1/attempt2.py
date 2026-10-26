from werkzeug.security import generate_password_hash

hashed = generate_password_hash("password", method="pbkdf2")  # DOC-LITERAL
assert hashed.startswith("pbkdf2:sha256:600000"), "default PBKDF2 is pbkdf2:sha256:600000"  # DOC-LITERAL

print("DOCS_OK")
