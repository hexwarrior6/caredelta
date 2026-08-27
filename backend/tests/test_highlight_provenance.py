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


def test_highlights_have_resolvable_provenance_pointers() -> None:
    response = client.get(f"/api/patients/{PATIENT_ID}/record", headers=AUTH_HEADERS)

    assert response.status_code == 200
    record = response.json()
    entries = {entry["id"]: entry for entry in record["timeline_entries"]}

    assert record["highlights"]
    for highlight in record["highlights"]:
        pointer = highlight["provenance_pointer"]
        source_entry = entries[pointer["entry_id"]]
        resolved_span = source_entry["content"][
            pointer["start_offset"] : pointer["end_offset"]
        ]

        assert pointer["source_quote"]
        assert pointer["end_offset"] > pointer["start_offset"]
        assert pointer["offset_confidence"] in {"high", "medium", "low"}
        assert resolved_span == pointer["source_quote"]


def test_scenario_a_top_highlight_points_to_patient_check_in_span() -> None:
    record = client.get(f"/api/patients/{PATIENT_ID}/record", headers=AUTH_HEADERS).json()
    highlight = next(item for item in record["highlights"] if item["id"] == "highlight-reliever")
    pointer = highlight["provenance_pointer"]
    source_entry = next(
        item for item in record["timeline_entries"] if item["id"] == pointer["entry_id"]
    )

    assert source_entry["id"] == "entry-2026-08-26-patient"
    assert pointer["offset_confidence"] == "high"
    assert source_entry["content"][
        pointer["start_offset"] : pointer["end_offset"]
    ] == "Reliever inhaler used five days this week."
