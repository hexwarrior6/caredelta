import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_adapter, get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)


class ChatAdapter:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], clinical_context: str) -> str:
        self.messages.append(messages)
        assert "Asthma" in clinical_context
        return "Daily reliever use can be important. Please contact your care team for review."

    def extract(self, sanitized_transcript: str):
        raise ValueError("Exercise the deterministic extraction fallback")


def headers(role: str = "patient", actor_id: str = PATIENT_ID):
    return {
        "X-Actor-Id": actor_id,
        "X-Actor-Role": role,
        "X-Clinic-Id": CLINIC_ID,
    }


@pytest.fixture(autouse=True)
def isolated_services():
    repository = MemoryRepository([build_seed_record()])
    adapter = ChatAdapter()
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_llm_adapter] = lambda: adapter
    yield repository, adapter
    app.dependency_overrides.clear()


def test_patient_chat_is_redacted_saved_and_ingested(isolated_services) -> None:
    repository, adapter = isolated_services
    chat = client.post(
        f"/api/patients/{PATIENT_ID}/ai-chat",
        headers=headers(),
        json={"message": "My name is Elaine Tan and I used my reliever inhaler daily."},
    )

    assert chat.status_code == 200
    payload = chat.json()
    session_id = payload["session"]["id"]
    assert "name" in payload["redacted_phi_types"]
    assert "Elaine Tan" not in adapter.messages[0][-1]["content"]
    assert payload["session"]["messages"][0]["content"].startswith("My name is [REDACTED_NAME]")

    follow_up = client.post(
        f"/api/patients/{PATIENT_ID}/ai-chat",
        headers=headers(),
        json={"session_id": session_id, "message": "It happened again last night."},
    )
    assert follow_up.status_code == 200
    assert len(follow_up.json()["session"]["messages"]) == 4

    ingest = client.post(
        f"/api/patients/{PATIENT_ID}/ai-chat/{session_id}/ingest",
        headers=headers(),
    )
    assert ingest.status_code == 201
    result = ingest.json()
    assert result["entry"]["author_role"] == "system"
    assert result["entry"]["entry_type"] == "patient_session_summary"
    assert result["highlights"]
    assert all(item["provenance_pointer"]["entry_id"] == result["entry"]["id"] for item in result["highlights"])

    stored = repository.get_patient_record(PATIENT_ID)
    saved = next(item for item in stored.patient_chat_sessions if item.id == session_id)
    assert saved.ingested_entry_id == result["entry"]["id"]


def test_staff_cannot_use_patient_chat() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/ai-chat",
        headers=headers("staff", "staff-syn-chen"),
        json={"message": "Can I use the patient assistant?"},
    )
    assert response.status_code == 403
