import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)


def headers(role: str, actor_id: str) -> dict[str, str]:
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


def create_entry(role: str, actor_id: str, section: str, title: str) -> dict:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries",
        headers=headers(role, actor_id),
        json={"section": section, "title": title, "content": "Initial content."},
    )
    assert response.status_code == 201
    return response.json()


def test_two_roles_editing_separate_sections_do_not_overwrite_each_other() -> None:
    staff = create_entry("staff", "staff-syn-chen", "staff_note", "Nurse follow-up")
    clinician = create_entry(
        "clinician", "clinician-syn-lim", "clinician_section", "Clinical plan"
    )

    staff_edit = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{staff['id']}",
        headers=headers("staff", "staff-syn-chen"),
        json={"content": "Spirometry booking confirmed.", "expected_version": 1},
    )
    clinician_edit = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{clinician['id']}",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"content": "Continue inhaler pending review.", "expected_version": 1},
    )

    assert staff_edit.status_code == 200
    assert clinician_edit.status_code == 200
    record = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers("clinician", "clinician-syn-lim"),
    ).json()
    entries = {entry["id"]: entry for entry in record["timeline_entries"]}
    assert entries[staff["id"]]["content"] == "Spirometry booking confirmed."
    assert entries[clinician["id"]]["content"] == "Continue inhaler pending review."
    assert entries[staff["id"]]["version"] == 2
    assert entries[clinician["id"]]["version"] == 2


def test_same_section_stale_write_is_rejected_deterministically() -> None:
    entry = create_entry(
        "clinician", "clinician-syn-lim", "clinician_section", "Shared plan"
    )
    first = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{entry['id']}",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"content": "First accepted update.", "expected_version": 1},
    )
    stale = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/{entry['id']}",
        headers=headers("admin", "admin-syn-tan"),
        json={"content": "Stale competing update.", "expected_version": 1},
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Entry version does not match expected_version"

