from inspect import signature

from starlette.background import BackgroundTasks

assert signature(BackgroundTasks).parameters["tasks"].default == [], "docs say Signature: BackgroundTasks(tasks=[])"  # DOC-LITERAL

print("DOCS_OK")
