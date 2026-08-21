"""Backend server entrypoint for local development."""
import os
from pathlib import Path
import uvicorn
from .api import Settings, create_app

DB_PATH = Path(os.environ.get("SECURECLOUD_DB", "backend_data.sqlite"))
ORIGIN = os.environ.get("SECURECLOUD_ORIGIN", "http://127.0.0.1:5173")

settings = Settings(
    database=DB_PATH,
    origin=ORIGIN,
    secure_cookie=False,  # Allow loopback development cookies
    session_seconds=86400,
    tenant_limit=10,
)

app = create_app(settings)

if __name__ == "__main__":
    print("[SecureCloud] Starting Zero Trust Management API on http://127.0.0.1:8000 ...")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)

