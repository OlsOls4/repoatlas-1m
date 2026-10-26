from werkzeug.debug import DebuggedApplication

app = lambda environ, start_response: []
debugger = DebuggedApplication(app)
# DOC-LITERAL-BEGIN
assert debugger.trusted_hosts == [".localhost"], "docs: default only allows .localhost domains"
# DOC-LITERAL-END
print("DOCS_OK")
