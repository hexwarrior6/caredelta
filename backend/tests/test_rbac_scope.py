import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)


def headers(role: str, actor_id: str | None = None, clinic_id: str = CLINIC_ID):
    return {
        "X-Actor-Id": actor_id or f"demo-{role}",
        "X-Actor-Role": role,
        "X-Clinic-Id": clinic_id,
    }


@pytest.fixture(autouse=True)
def isolated_repository():
    repository = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: repository
    yield repository
    app.dependency_overrides.clear()


def test_patient_cannot_read_raw_ai_notes_or_internal_comments() -> None:
    response = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers("patient", PATIENT_ID)
    )

    assert response.status_code == 200
    record = response.json()
    assert record["comments"] == []
    assert record["audit_logs"] == []
    assert record["timeline_entries"]
    assert {entry["entry_type"] for entry in record["timeline_entries"]} <= {
        "patient_instruction",
        "patient_session_summary",
    }
    assert not any(
        entry["entry_type"] in {"staff_note", "clinician_note"}
        for entry in record["timeline_entries"]
    )
    assert all(
        not entry["entry_type"].startswith("ai_")
        for entry in record["timeline_entries"]
    )


def test_staff_read_view_excludes_clinician_and_raw_ai_content() -> None:
    response = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers("staff")
    )

    assert response.status_code == 200
    record = response.json()
    entry_types = {entry["entry_type"] for entry in record["timeline_entries"]}
    assert "staff_note" in entry_types
    assert "patient_session_summary" in entry_types
    assert "clinician_note" not in entry_types
    assert not any(entry_type.startswith("ai_") for entry_type in entry_types)
    assert record["comments"]


def test_auth_context_is_required() -> None:
    response = client.get(f"/api/patients/{PATIENT_ID}/record")

    assert response.status_code == 401


def test_staff_cannot_create_or_edit_clinician_section() -> None:
    create_response = client.post(
        f"/api/patients/{PATIENT_ID}/entries",
        headers=headers("staff", "staff-syn-chen"),
        json={
            "section": "clinician_section",
            "title": "Unauthorized plan",
            "content": "Staff must not create this section.",
        },
    )
    edit_response = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2025-04-15",
        headers=headers("staff", "staff-syn-chen"),
        json={"content": "Unauthorized overwrite", "expected_version": 1},
    )

    assert create_response.status_code == 403
    assert edit_response.status_code == 403


def test_clinician_cannot_overwrite_staff_note() -> None:
    response = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"content": "Unauthorized overwrite", "expected_version": 1},
    )

    assert response.status_code == 403


def test_clinician_can_edit_only_their_own_clinician_note() -> None:
    own_note = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2025-04-15",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"content": "Updated asthma review.", "expected_version": 1},
    )
    someone_elses_note = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2025-04-15",
        headers=headers("clinician", "clinician-syn-other"),
        json={"content": "Unauthorized overwrite.", "expected_version": 2},
    )

    assert own_note.status_code == 200
    assert own_note.json()["version"] == 2
    assert someone_elses_note.status_code == 403


def test_admin_can_edit_any_timeline_entry_type() -> None:
    response = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-26-patient",
        headers=headers("admin", "admin-syn-morgan"),
        json={"content": "Administrator-corrected patient entry.", "expected_version": 1},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2


def test_staff_can_edit_only_their_own_staff_note() -> None:
    allowed = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27",
        headers=headers("staff", "staff-syn-chen"),
        json={"content": "Spirometry booking is in progress.", "expected_version": 1},
    )
    denied = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27",
        headers=headers("staff", "different-staff"),
        json={"content": "Unauthorized overwrite", "expected_version": 2},
    )

    assert allowed.status_code == 200
    assert allowed.json()["version"] == 2
    assert denied.status_code == 403


@pytest.mark.parametrize("role", ["patient", "staff", "clinician", "admin"])
def test_every_role_is_rejected_outside_its_clinic_scope(role: str) -> None:
    response = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers(role, clinic_id="clinic-syn-other"),
    )

    assert response.status_code == 403
