import pytest
from fastapi.testclient import TestClient
from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import build_seed_records

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_repository():
    repository = MemoryRepository(build_seed_records())
    app.dependency_overrides[get_repository] = lambda: repository
    yield repository
    app.dependency_overrides.clear()

def test_demo_login_issues_signed_session_and_patient_isolation():
    identities = client.get("/api/demo/identities")
    assert identities.status_code == 200
    assert len(identities.json()) == 6

    login = client.post(
        "/api/demo/login",
        json={"identity_id": "patient-syn-002", "demo_key": "AMIR-DEMO-2026"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    own = client.get("/api/patients/patient-syn-002/record", headers=headers)
    other = client.get("/api/patients/patient-syn-001/record", headers=headers)

    assert own.status_code == 200
    assert own.json()["patient"]["display_name"] == "Amir Rahman"
    assert other.status_code == 403

def test_invalid_demo_key_and_tampered_token_are_rejected():
    invalid = client.post(
        "/api/demo/login",
        json={"identity_id": "clinician-syn-lim", "demo_key": "wrong"},
    )
    assert invalid.status_code == 401

    tampered = client.get(
        "/api/patients/patient-syn-001/record",
        headers={"Authorization": "Bearer forged.token"},
    )
    assert tampered.status_code == 401
