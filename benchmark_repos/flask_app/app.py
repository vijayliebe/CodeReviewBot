from flask import Flask

DEBUG = True
SECRET_KEY = "flask-hardcoded-secret-key-xyz-1234567890"

app = Flask(__name__)
app.config.from_object(__name__)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/internal")
@csrf_exempt
def internal():
    # VIOLATION (no-print-statements)
    print("internal endpoint hit")
    return {"ok": True}
