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
    tenant_limit=int(os.environ.get("SECURECLOUD_TENANT_LIMIT", "2")),
    infrastructure=os.environ.get("SECURECLOUD_INFRASTRUCTURE", "disabled"),
    kubeconfig=Path(os.environ["SECURECLOUD_KUBECONFIG"]) if os.environ.get("SECURECLOUD_KUBECONFIG") else None,
    kube_api=os.environ.get("SECURECLOUD_KUBE_API"),
    retail_manifest=(
        Path(os.environ["SECURECLOUD_RETAIL_MANIFEST"])
        if os.environ.get("SECURECLOUD_RETAIL_MANIFEST")
        else None
    ),
    hubble_export=Path(os.environ["SECURECLOUD_HUBBLE_EXPORT"]) if os.environ.get("SECURECLOUD_HUBBLE_EXPORT") else None,
    temporal_model=Path(os.environ["SECURECLOUD_TEMPORAL_MODEL"]) if os.environ.get("SECURECLOUD_TEMPORAL_MODEL") else None,
)

app = create_app(settings)

if __name__ == "__main__":
    print("[SecureCloud] Starting Zero Trust Management API on http://127.0.0.1:8000 ...")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)

