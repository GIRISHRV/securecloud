from fastapi.testclient import TestClient

from backend.reference_apps.app import MAX_BODY_BYTES, create_reference_app, repository_from_environment
from backend.reference_apps.repository import MemoryRecordRepository


def client(profile: str = "hospital") -> TestClient:
    return TestClient(create_reference_app(profile_id=profile, repository=MemoryRecordRepository()))


def test_profiles_expose_only_their_allowlisted_resources():
    hospital = client("hospital")
    college = client("college")

    assert [item["id"] for item in hospital.get("/api/profile").json()["resources"]] == [
        "patients",
        "doctors",
        "appointments",
    ]
    assert college.get("/api/resources/students").status_code == 200
    assert college.get("/api/resources/patients").status_code == 404
    patient_fields = hospital.get("/api/profile").json()["resources"][0]["fields"]
    assert [field["id"] for field in patient_fields] == [
        "full_name", "patient_number", "date_of_birth", "phone"
    ]


def test_create_update_list_delete_and_summary_flow():
    api = client()
    created = api.post(
        "/api/resources/patients",
        json={
            "full_name": "Maya Rao",
            "patient_number": "PAT-104",
            "date_of_birth": "1996-04-12",
            "phone": "+91 98765 43210",
        },
    )

    assert created.status_code == 201
    assert created.json()["resource"] == "patients"
    record_id = created.json()["id"]
    updated = api.put(
        f"/api/resources/patients/{record_id}",
        json={**created.json(), "full_name": "Maya R. Rao", "id": record_id, "resource": "patients"},
    )
    assert updated.status_code == 422
    updated = api.put(
        f"/api/resources/patients/{record_id}",
        json={
            "full_name": "Maya R. Rao",
            "patient_number": "PAT-104",
            "date_of_birth": "1996-04-12",
            "phone": "+91 98765 43210",
        },
    )
    assert updated.status_code == 200
    assert api.get("/api/resources/patients").json()["items"] == [updated.json()]
    assert api.get("/api/summary").json()["counts"]["patients"] == 1
    assert api.delete(f"/api/resources/patients/{record_id}").status_code == 204
    assert api.get("/api/summary").json()["counts"]["patients"] == 0
    assert api.delete(f"/api/resources/patients/{record_id}").status_code == 404


def test_request_validation_rejects_extra_missing_and_invalid_fields():
    api = client()
    extra = api.post(
        "/api/resources/patients",
        json={"full_name": "Patient", "role": "admin"},
    )
    missing = api.post("/api/resources/patients", json={"full_name": "Patient"})
    invalid_phone = api.post("/api/resources/patients", json={
        "full_name": "Patient", "patient_number": "P-1", "date_of_birth": "2000-01-01", "phone": "123"
    })
    invalid_date = api.post("/api/resources/patients", json={
        "full_name": "Patient", "patient_number": "P-1", "date_of_birth": "not-a-date", "phone": "9876543210"
    })

    assert extra.status_code == 422
    assert missing.status_code == 422
    assert invalid_phone.status_code == 422
    assert invalid_date.status_code == 422
    assert api.get("/api/summary").json()["counts"]["patients"] == 0


def test_domain_specific_email_and_choice_validation():
    college = client("college")
    assert college.post("/api/resources/faculty", json={
        "full_name": "Anita Shah", "employee_id": "FAC-7", "subject": "Physics", "email": "invalid"
    }).status_code == 422
    assert college.post("/api/resources/attendance", json={
        "student_name": "Rohan Das", "class_name": "10-A", "attendance_date": "2026-11-13", "status": "Unknown"
    }).status_code == 422


def test_large_request_is_rejected_before_handler():
    api = client()
    response = api.post(
        "/api/resources/patients",
        content=b"x" * (MAX_BODY_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_security_headers_are_present():
    response = client().get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_runtime_storage_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("APP_STORAGE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        repository_from_environment()
    except RuntimeError as error:
        assert "PostgreSQL configuration is required" in str(error)
    else:
        raise AssertionError("missing database configuration must fail startup")
