from fastapi.testclient import TestClient

from app.main import app
from app.seed import PATIENT_ID


client = TestClient(app)


def test_complete_seed_patient_record_is_returned() -> None:
    response = client.get(f"/api/patients/{PATIENT_ID}/record")

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
    record = client.get(f"/api/patients/{PATIENT_ID}/record").json()
    entries = {entry["id"]: entry for entry in record["timeline_entries"]}

    for highlight in record["highlights"]:
        pointer = highlight["provenance_pointer"]
        content = entries[pointer["entry_id"]]["content"]
        resolved = content[pointer["start_offset"] : pointer["end_offset"]]
        assert resolved == pointer["source_quote"]


def test_unknown_patient_returns_404() -> None:
    response = client.get("/api/patients/unknown/record")

    assert response.status_code == 404
