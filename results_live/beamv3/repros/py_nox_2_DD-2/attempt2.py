import types

import nox
from nox.manifest import Manifest
from nox.tasks import filter_manifest


@nox.session(default=False)
def hidden(session):
    pass


config = types.SimpleNamespace(
    sessions=None,
    list_sessions=False,
    pythons=None,
    tags=None,
    keywords=None,
    noxfile="noxfile.py",
)
manifest = Manifest([hidden], config, None)
result = filter_manifest(manifest, config)
assert isinstance(result, Manifest) or result == 3, "filter_manifest should return 3 or the manifest"  # DOC-LITERAL
print("DOCS_OK")
