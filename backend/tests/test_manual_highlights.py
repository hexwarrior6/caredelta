import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)
ENTRY_ID = "entry-2026-02-06"
QUOTE = "night-time wheeze on three evenings this week"


def headers(role: str, actor_id: str, clinic_id: str = CLINIC_ID) -> dict[str, str]:
    return {
        "X-Actor-Id": actor_id,
        "X-Actor-Role": role,
        "X-Clinic-Id": clinic_id,
    }


@pytest.fixture(autouse=True)
def isolated_repository():
    repository = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: repository
    yield repository
    app.dependency_overrides.clear()


def selection_payload(*, quote: str = QUOTE, start_delta: int = 0) -> dict:
    record = build_seed_record()
    entry = next(item for item in record.timeline_entries if item.id == ENTRY_ID)
    start = entry.content.index(QUOTE) + start_delta
    return {
        "source_quote": quote,
        "start_offset": start,
        "end_offset": start + len(quote),
        "category": "worsening",
        "risk_level": "low",
        "risk_reason": "Repeated night symptoms may indicate reduced asthma control.",
    }


def test_clinician_creates_confirmed_highlight_from_exact_ai_note_span(
    isolated_repository: MemoryRepository,
) -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers("clinician", "clinician-syn-lim"),
        json=selection_payload(),
    )

    assert response.status_code == 201
    highlight = response.json()
    assert highlight["text"] == QUOTE
    assert highlight["trust_status"] == "clinician_confirmed"
    assert highlight["reviewed_by"] == "clinician-syn-lim"
    assert highlight["reviewed_by_role"] == "clinician"
    assert highlight["reviewed_at"]
    assert highlight["provenance_pointer"]["source_type"] == "manual_selection"
    assert highlight["provenance_pointer"]["entry_id"] == ENTRY_ID
    assert highlight["provenance_pointer"]["offset_confidence"] == "high"
    assert highlight["risk_level"] == "medium"
    assert highlight["risk_floor_applied"] is True

    stored = isolated_repository.get_patient_record(PATIENT_ID)
    assert stored is not None
    stored_highlight = next(item for item in stored.highlights if item.id == highlight["id"])
    pointer = stored_highlight.provenance_pointer
    source = next(item for item in stored.timeline_entries if item.id == ENTRY_ID)
    assert source.content[pointer.start_offset : pointer.end_offset] == pointer.source_quote
    audit = stored.audit_logs[-1]
    assert audit.action == "create_manual_highlight"
    assert audit.entity_id == highlight["id"]
    assert "provenance_pointer" in audit.changed_fields
    assert not hasattr(audit, "source_quote")


def test_manual_highlight_appears_in_clinician_glance_but_raw_source_stays_hidden_from_patient() -> None:
    created = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers("clinician", "clinician-syn-lim"),
        json=selection_payload(),
    ).json()

    clinician_record = client.get(
        f"/api/patients/{PATIENT_ID}/record?highlight_page_size=6",
        headers=headers("clinician", "clinician-syn-lim"),
    ).json()
    assert created["id"] in {item["id"] for item in clinician_record["highlights"]}

    patient_record = client.get(
        f"/api/patients/{PATIENT_ID}/record?highlight_page_size=6",
        headers=headers("patient", PATIENT_ID),
    ).json()
    assert created["id"] not in {item["id"] for item in patient_record["highlights"]}
    assert ENTRY_ID not in {item["id"] for item in patient_record["timeline_entries"]}


@pytest.mark.parametrize(
    ("role", "actor_id"),
    [("patient", PATIENT_ID), ("staff", "staff-syn-chen")],
)
def test_patient_and_staff_cannot_create_manual_highlight(role: str, actor_id: str) -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers(role, actor_id),
        json=selection_payload(),
    )

    assert response.status_code == 403


def test_manual_highlight_enforces_clinic_scope() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers("clinician", "clinician-syn-lim", "clinic-syn-other"),
        json=selection_payload(),
    )

    assert response.status_code == 403


def test_server_rejects_stale_or_tampered_source_offsets() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers("clinician", "clinician-syn-lim"),
        json=selection_payload(start_delta=1),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Selected text no longer matches the stored source"


def test_manual_highlight_is_limited_to_ai_scribed_entries() -> None:
    record = build_seed_record()
    entry = next(item for item in record.timeline_entries if item.id == "entry-2025-04-15")
    quote = "Asthma symptoms remain mild"
    start = entry.content.index(quote)
    payload = selection_payload()
    payload.update(
        {"source_quote": quote, "start_offset": start, "end_offset": start + len(quote)}
    )
    response = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{entry.id}/highlights",
        headers=headers("clinician", "clinician-syn-lim"),
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Manual highlights can be created only from AI-scribed entries"


def test_exact_duplicate_source_span_is_rejected() -> None:
    first = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers("admin", "admin-syn-morgan"),
        json=selection_payload(),
    )
    duplicate = client.post(
        f"/api/patients/{PATIENT_ID}/entries/{ENTRY_ID}/highlights",
        headers=headers("clinician", "clinician-syn-lim"),
        json=selection_payload(),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "This exact source span is already highlighted"
