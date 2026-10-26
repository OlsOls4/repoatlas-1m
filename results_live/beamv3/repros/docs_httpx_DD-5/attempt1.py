from flask import Flask
import httpx

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello World!"

client = httpx.Client(app=app)  # DOC-LITERAL
print("DOCS_OK")
