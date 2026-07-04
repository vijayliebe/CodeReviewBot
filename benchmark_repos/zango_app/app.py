from zango.apps import ZangoApp
from zango.config import settings

DEBUG = True
SECRET_KEY = "zango-hardcoded-secret-key-abcdef123456"

app = ZangoApp(__name__)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/internal")
def internal():
    # VIOLATION (no-print-statements)
    print("internal endpoint hit")
    return {"ok": True}
