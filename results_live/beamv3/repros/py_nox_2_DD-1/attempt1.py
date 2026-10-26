from nox.tasks import run_manifest

class Manifest:
    def list_all_sessions(self):
        return []

class GlobalConfig:
    parallel = 1

manifest = Manifest()
global_config = GlobalConfig()
result = run_manifest(manifest, global_config)  # DOC-LITERAL
assert isinstance(result, tuple) and len(result) == 2  # DOC-LITERAL
print("DOCS_OK")
