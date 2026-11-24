from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse

from .profiles import ProfileSpec, ResourceSpec, get_profile
from .repository import MemoryRecordRepository, PostgresRecordRepository, RecordRepository

MAX_BODY_BYTES = 16 * 1024


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_PATTERN = re.compile(r"^[+0-9() .-]+$")


def repository_from_environment() -> RecordRepository:
    if os.environ.get("APP_STORAGE") == "memory":
        return MemoryRecordRepository()
    connection_string = os.environ.get("DATABASE_URL")
    postgres_environment = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")
    if not connection_string and not all(os.environ.get(name) for name in postgres_environment):
        raise RuntimeError("PostgreSQL configuration is required unless APP_STORAGE=memory")
    return PostgresRecordRepository(connection_string or "")


def create_reference_app(
    *,
    profile_id: str | None = None,
    repository: RecordRepository | None = None,
) -> FastAPI:
    profile = get_profile(profile_id or os.environ.get("APP_PROFILE", "hospital"))
    records = repository or repository_from_environment()
    app = FastAPI(
        title=f"{profile.name} API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def request_boundary(request: Request, call_next: Callable):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_BODY_BYTES:
                    return JSONResponse({"detail": "Request body is too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def require_resource(resource_id: str) -> ResourceSpec:
        resource = profile.resource(resource_id)
        if resource is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        return resource

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "profile": profile.id}

    @app.get("/api/profile")
    def read_profile() -> dict[str, object]:
        return profile_payload(profile)

    @app.get("/api/summary")
    def read_summary() -> dict[str, object]:
        resource_ids = tuple(resource.id for resource in profile.resources)
        return {"profile": profile.id, "counts": records.counts(resource_ids)}

    @app.get("/api/resources/{resource_id}")
    def list_records(resource_id: str) -> dict[str, object]:
        require_resource(resource_id)
        return {"items": [record.to_dict() for record in records.list(resource_id)]}

    @app.post("/api/resources/{resource_id}", status_code=201)
    def create_record(resource_id: str, body: dict[str, object]) -> dict[str, object]:
        resource = require_resource(resource_id)
        record = records.create(resource_id, validate_payload(resource, body)).to_dict()
        if resource_id == "orders" and os.environ.get("PLATFORM_NAMESPACE"):
            record["platform"] = settle_with_platform(profile.id, record)
        return record

    @app.put("/api/resources/{resource_id}/{record_id}")
    def update_record(
        resource_id: str,
        body: dict[str, object],
        record_id: int = Path(ge=1),
    ) -> dict[str, object]:
        resource = require_resource(resource_id)
        record = records.update(resource_id, record_id, validate_payload(resource, body))
        if record is None:
            raise HTTPException(status_code=404, detail="Record not found")
        return record.to_dict()

    @app.delete("/api/resources/{resource_id}/{record_id}", status_code=204)
    def delete_record(resource_id: str, record_id: int = Path(ge=1)) -> None:
        require_resource(resource_id)
        if not records.delete(resource_id, record_id):
            raise HTTPException(status_code=404, detail="Record not found")

    return app


def _post(service: str, resource: str, body: dict) -> dict:
    url = f"http://{service}.{os.environ['PLATFORM_NAMESPACE']}.svc.cluster.local:8080/api/resources/{resource}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def settle_with_platform(shop: str, order: dict) -> dict:
    """Order IDs -> Payments -> Email, through the shared platform zone. Each step is reported."""
    result: dict = {}
    try:
        issued = _post("order-ids", "ids", {"shop": shop, "shop_order": str(order.get("order_number", ""))})
        result["order_id"] = f"MALL-{issued['id']:06d}"
        _post("payments", "payments", {"order_id": result["order_id"], "shop": shop,
                                       "amount": str(order.get("total", "0")), "status": "Captured"})
        result["payment"] = "Captured"
        _post("email", "emails", {"to": str(order.get("customer_email", "")),
                                  "subject": f"Your {shop} order {result['order_id']} is confirmed"})
        result["email"] = "Queued"
    except Exception as exc:  # report the failing step instead of failing the order
        result["error"] = type(exc).__name__
    return result


def profile_payload(profile: ProfileSpec) -> dict[str, object]:
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "resources": [
            {
                "id": resource.id,
                "singular": resource.singular,
                "label": resource.label,
                "description": resource.description,
                "fields": [
                    {
                        "id": field.id,
                        "label": field.label,
                        "kind": field.kind,
                        "required": field.required,
                        "maxLength": field.max_length,
                        "options": list(field.options),
                    }
                    for field in resource.fields
                ],
            }
            for resource in profile.resources
        ],
    }


def validate_payload(resource: ResourceSpec, body: dict[str, object]) -> dict[str, str]:
    allowed = {field.id for field in resource.fields}
    unexpected = sorted(set(body) - allowed)
    if unexpected:
        raise HTTPException(status_code=422, detail=f"Unexpected field: {unexpected[0]}")

    result: dict[str, str] = {}
    for field in resource.fields:
        raw_value = body.get(field.id)
        if not isinstance(raw_value, str):
            raise HTTPException(status_code=422, detail=f"{field.label} is required")
        value = raw_value.strip()
        if field.required and not value:
            raise HTTPException(status_code=422, detail=f"{field.label} is required")
        if len(value) > field.max_length:
            raise HTTPException(status_code=422, detail=f"{field.label} is too long")
        if field.options and value not in field.options:
            raise HTTPException(status_code=422, detail=f"{field.label} is not allowed")
        if field.kind == "email" and not EMAIL_PATTERN.fullmatch(value):
            raise HTTPException(status_code=422, detail=f"{field.label} is invalid")
        if field.kind == "tel" and (not PHONE_PATTERN.fullmatch(value) or sum(char.isdigit() for char in value) < 7):
            raise HTTPException(status_code=422, detail=f"{field.label} is invalid")
        if field.kind == "date":
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"{field.label} is invalid") from exc
        if field.kind == "datetime-local":
            try:
                datetime.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"{field.label} is invalid") from exc
        result[field.id] = value
    return result


def create_app_from_environment() -> FastAPI:
    return create_reference_app()
