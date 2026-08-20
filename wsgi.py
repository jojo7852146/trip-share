"""gunicorn entry point for Render / production."""
from server import app
import db

db.init_db()

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
