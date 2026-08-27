import json

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)
STAFF_HEADERS = {
    "X-Actor-Id": "staff-syn-chen",
    "X-Actor-Role": "staff",
    "X-Clinic-Id": CLINIC_ID,
}


@pytest.fixture(autouse=True)
def isolated_repository():
    repository = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: repository
    yield
    app.dependency_overrides.clear()


def create_staff_note(initial_content: str = "Initial full note snapshot.") -> dict:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries",
        headers=STAFF_HEADERS,
        json={
            "section": "staff_note",
            "title": "Revision demo",
            "content": initial_content,
        },
    )
    assert response.status_code == 201
    return response.json()


def get_staff_record() -> dict:
    response = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=STAFF_HEADERS
    )
    assert response.status_code == 200
    return response.json()


def test_edit_increments_version_and_preserves_full_snapshots() -> None:
    note = create_staff_note()
    edited_content = "Edited full note snapshot with complete clinical context."

    response = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{note['id']}",
        headers=STAFF_HEADERS,
        json={"content": edited_content, "expected_version": 1},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    record = get_staff_record()
    versions = sorted(
        (item for item in record["versions"] if item["entry_id"] == note["id"]),
        key=lambda item: item["version_number"],
    )
    assert [item["version_number"] for item in versions] == [1, 2]
    assert [item["content_snapshot"] for item in versions] == [
        "Initial full note snapshot.",
        edited_content,
    ]


def test_revert_creates_new_version_and_restores_old_content() -> None:
    original = "Original note content that must remain recoverable."
    note = create_staff_note(original)
    edited = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{note['id']}",
        headers=STAFF_HEADERS,
        json={"content": "Replacement content.", "expected_version": 1},
    )
    assert edited.status_code == 200

    reverted = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{note['id']}/revert",
        headers=STAFF_HEADERS,
        json={"target_version": 1, "expected_version": 2},
    )

    assert reverted.status_code == 200
    assert reverted.json()["version"] == 3
    assert reverted.json()["content"] == original
    record = get_staff_record()
    versions = sorted(
        (item for item in record["versions"] if item["entry_id"] == note["id"]),
        key=lambda item: item["version_number"],
    )
    assert [item["version_number"] for item in versions] == [1, 2, 3]
    assert versions[-1]["content_snapshot"] == original
    assert versions[-1]["change_summary"] == "Reverted to version 1"


def test_revert_rejects_stale_version_and_audit_contains_metadata_only() -> None:
    secret_body = "FULL RAW NOTE BODY MUST NOT APPEAR IN AUDIT"
    note = create_staff_note(secret_body)
    edited = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{note['id']}",
        headers=STAFF_HEADERS,
        json={"content": "Safe edited content.", "expected_version": 1},
    )
    assert edited.status_code == 200

    stale = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{note['id']}/revert",
        headers=STAFF_HEADERS,
        json={"target_version": 1, "expected_version": 1},
    )
    assert stale.status_code == 409

    repository = app.dependency_overrides[get_repository]()
    stored = repository.get_patient_record(PATIENT_ID)
    assert stored is not None
    audits = [audit for audit in stored.audit_logs if audit.entity_id == note["id"]]
    assert [audit.action for audit in audits] == ["create_entry", "update_entry"]
    serialized_audits = json.dumps(
        [audit.model_dump(mode="json") for audit in audits]
    )
    assert secret_body not in serialized_audits
    assert "Safe edited content." not in serialized_audits
    assert "content_snapshot" not in serialized_audits


def test_patient_cannot_revert_internal_note() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27/revert",
        headers={
            "X-Actor-Id": PATIENT_ID,
            "X-Actor-Role": "patient",
            "X-Clinic-Id": CLINIC_ID,
        },
        json={"target_version": 1, "expected_version": 1},
    )

    assert response.status_code == 403
