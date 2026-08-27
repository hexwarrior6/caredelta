import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)


def headers(role: str, actor_id: str):
    return {
        "X-Actor-Id": actor_id,
        "X-Actor-Role": role,
        "X-Clinic-Id": CLINIC_ID,
    }


@pytest.fixture(autouse=True)
def isolated_repository():
    repository = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: repository
    yield
    app.dependency_overrides.clear()


def test_staff_to_clinician_collaboration_flow() -> None:
    staff_headers = headers("staff", "staff-syn-chen")
    clinician_headers = headers("clinician", "clinician-syn-lim")

    note_response = client.post(
        f"/api/patients/{PATIENT_ID}/entries",
        headers=staff_headers,
        json={
            "section": "staff_note",
            "title": "Phone follow-up",
            "content": "Patient reports waking twice overnight with wheeze.",
        },
    )
    assert note_response.status_code == 201
    note = note_response.json()

    comment_response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{note['id']}/comments",
        headers=staff_headers,
        json={
            "body": "@clinician Please review the overnight symptoms.",
            "mentions": ["clinician-syn-lim"],
            "assigned_role": "clinician",
        },
    )
    assert comment_response.status_code == 201
    comment = comment_response.json()
    assert comment["resolved"] is False
    assert comment["assigned_role"] == "clinician"

    clinician_record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=clinician_headers
    )
    assert clinician_record.status_code == 200
    payload = clinician_record.json()
    assert any(item["id"] == note["id"] for item in payload["timeline_entries"])
    assert any(item["id"] == comment["id"] for item in payload["comments"])

    resolved = client.patch(
        f"/api/patients/{PATIENT_ID}/comments/{comment['id']}",
        headers=clinician_headers,
        json={"resolved": True},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved"] is True

    reopened = client.patch(
        f"/api/patients/{PATIENT_ID}/comments/{comment['id']}",
        headers=clinician_headers,
        json={"resolved": False},
    )
    assert reopened.status_code == 200
    assert reopened.json()["resolved"] is False


def test_patient_cannot_create_or_resolve_internal_comments() -> None:
    patient_headers = headers("patient", PATIENT_ID)

    create_response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27/comments",
        headers=patient_headers,
        json={"body": "Should remain internal."},
    )
    resolve_response = client.patch(
        f"/api/patients/{PATIENT_ID}/comments/comment-001",
        headers=patient_headers,
        json={"resolved": True},
    )

    assert create_response.status_code == 403
    assert resolve_response.status_code == 403
