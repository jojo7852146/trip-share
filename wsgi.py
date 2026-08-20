"""gunicorn entry point for Render / production."""
from server import app

# Initialize DB tables on startup (safe to call multiple times).
# Wrap in try/except so build-time imports (without DATABASE_URL)
# don't crash the deploy.
try:
    import db

    db.init_db()
except Exception:
    import logging

    logging.getLogger("trip-share.wsgi").warning(
        "db.init_db() skipped (DATABASE_URL may not be set yet)",
        exc_info=True,
    )

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
