"""gunicorn entry point for Render / production.

IMPORTANT: do NOT call db.init_db() here. On Render the database DNS may
not be ready when the process starts; calling init_db() at import time
blocks startup for the whole retry window (minutes), so Render's health
check times out and the deploy stays in "Deploying" forever.

Table creation is deferred to the first real API request via the
before_request hook in server.py. /health and /_debug/env skip it, so the
deploy health check always returns instantly.
"""
from server import app

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
