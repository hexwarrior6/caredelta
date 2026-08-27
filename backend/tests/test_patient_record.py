import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import PATIENT_ID, build_seed_record


client = TestClient(app)
AUTH_HEADERS = {
    "X-Actor-Id": "clinician-syn-lim",
    "X-Actor-Role": "clinician",
    "X-Clinic-Id": "clinic-syn-orchard",
}


@pytest.fixture(autouse=True)
def isolated_repository():
    repository = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: repository
    yield
    app.dependency_overrides.clear()


def test_complete_seed_patient_record_is_returned() -> None:
    response = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    record = response.json()
    assert record["patient"]["id"] == PATIENT_ID
    assert record["patient"]["synthetic"] is True

    required_collections = {
        "highlights",
        "tasks",
        "timeline_entries",
        "comments",
        "versions",
        "audit_logs",
        "interaction_events",
        "conflicts",
    }
    assert required_collections <= record.keys()
    assert all(record[name] for name in required_collections)


def test_every_highlight_provenance_resolves_to_exact_timeline_span() -> None:
    record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=AUTH_HEADERS
    ).json()
    entries = {entry["id"]: entry for entry in record["timeline_entries"]}

    for highlight in record["highlights"]:
        pointer = highlight["provenance_pointer"]
        content = entries[pointer["entry_id"]]["content"]
        resolved = content[pointer["start_offset"] : pointer["end_offset"]]
        assert resolved == pointer["source_quote"]


def test_unknown_patient_returns_404() -> None:
    response = client.get("/api/patients/unknown/record", headers=AUTH_HEADERS)

    assert response.status_code == 404
