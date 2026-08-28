import json

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_adapter, get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record
from app.services.ai_ingest import (
    AIExtraction,
    AISignal,
    DeepSeekAdapter,
    MockLLMAdapter,
    fallback_extract,
)


client = TestClient(app)


def headers(role: str = "clinician") -> dict[str, str]:
    return {
        "X-Actor-Id": "clinician-syn-lim",
        "X-Actor-Role": role,
        "X-Clinic-Id": CLINIC_ID,
    }


def successful_extraction() -> AIExtraction:
    return AIExtraction(
        title="Increased reliever use",
        summary="Reliever use increased.",
        signals=[
            AISignal(
                text="Daily reliever use",
                category="worsening",
                risk_level="high",
                risk_reason="May indicate reduced asthma control.",
                importance_score=92,
                extraction_confidence="high",
                confidence_reason="Explicit frequency increase with an exact source sentence.",
                source_snippet="Reliever inhaler used daily this week.",
            )
        ],
    )


@pytest.fixture
def repository():
    isolated = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: isolated
    yield isolated
    app.dependency_overrides.clear()


def test_llm_receives_no_name_phone_id_or_email(repository: MemoryRepository) -> None:
    adapter = MockLLMAdapter(response=successful_extraction())
    app.dependency_overrides[get_llm_adapter] = lambda: adapter
    raw_phi = {
        "name": "Elaine Tan",
        "phone": "+65 9123 4567",
        "id": "S1234567D",
        "email": "elaine.tan@example.com",
    }

    response = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json={
            "title": "Respiratory follow-up",
            "source_id": "session-private-001",
            "interaction_type": "ai_doctor_consult_summary",
            "transcript": (
                f"{raw_phi['name']} phone {raw_phi['phone']}; ID {raw_phi['id']}; "
                f"email {raw_phi['email']}. Reliever inhaler used daily this week."
            ),
        },
    )

    assert response.status_code == 201
    assert response.json()["extraction_method"] == "deepseek"
    assert response.json()["entry"]["title"] == "Increased reliever use"
    assert set(response.json()["redacted_phi_types"]) == {
        "email",
        "id",
        "name",
        "phone",
    }
    for value in raw_phi.values():
        assert value not in adapter.received_transcripts[0]
        assert value not in response.json()["entry"]["content"]


def test_deepseek_failure_creates_fallback_highlight_and_system_entry(
    repository: MemoryRepository,
) -> None:
    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter(
        error=TimeoutError("simulated DeepSeek timeout")
    )
    transcript = "Patient reports wheeze at night. Reliever inhaler used every day."

    response = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json={
            "source_id": "session-fallback-001",
            "interaction_type": "ai_nurse_consult_summary",
            "transcript": transcript,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["extraction_method"] == "fallback"
    assert payload["fallback_reason"] == "timeout"
    assert payload["highlights"]
    assert payload["entry"]["author_role"] == "system"
    assert payload["entry"]["entry_type"] == "ai_nurse_consult_summary"
    assert payload["entry"]["title"] == "Worsening symptoms requiring review"
    pointer = payload["highlights"][0]["provenance_pointer"]
    assert pointer["entry_id"] == payload["entry"]["id"]
    assert payload["entry"]["content"][pointer["start_offset"] : pointer["end_offset"]] == pointer["source_quote"]

    stored = repository.get_patient_record(PATIENT_ID)
    assert stored is not None
    assert any(item.id == payload["entry"]["id"] for item in stored.timeline_entries)
    assert any(item.id == payload["highlights"][0]["id"] for item in stored.highlights)
    audit = next(item for item in stored.audit_logs if item.entity_id == payload["entry"]["id"])
    assert transcript not in audit.model_dump_json()

    clinician_record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers()
    ).json()
    assert any(
        item["id"] == payload["entry"]["id"]
        and item["author_role"] == "system"
        for item in clinician_record["timeline_entries"]
    )


def test_patient_cannot_ingest_ai_note(repository: MemoryRepository) -> None:
    app.dependency_overrides[get_llm_adapter] = lambda: None
    response = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers("patient"),
        json={
            "source_id": "session-unauthorized",
            "interaction_type": "ai_patient_session_summary",
            "transcript": "New note.",
        },
    )
    assert response.status_code == 403


def test_invalid_json_and_unresolved_provenance_trigger_fallback(
    repository: MemoryRepository,
) -> None:
    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter(
        error=ValueError("invalid JSON")
    )
    body = {
        "source_id": "session-invalid-json",
        "interaction_type": "ai_doctor_consult_summary",
        "transcript": "Reliever inhaler use remains unresolved.",
    }
    invalid = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest", headers=headers(), json=body
    )
    assert invalid.status_code == 201
    assert invalid.json()["extraction_method"] == "fallback"
    assert invalid.json()["fallback_reason"] == "invalid_json"

    ungrounded = successful_extraction().model_copy(
        update={
            "signals": [
                successful_extraction().signals[0].model_copy(
                    update={"source_snippet": "This sentence is not in the transcript."}
                )
            ]
        }
    )
    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter(
        response=ungrounded
    )
    unresolved_body = {
        **body,
        "source_id": "session-unresolved-provenance",
    }
    unresolved = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json=unresolved_body,
    )
    assert unresolved.status_code == 201
    assert unresolved.json()["fallback_reason"] == "provenance_unresolved"


def test_redaction_preview_and_full_ingest_integration(
    repository: MemoryRepository,
) -> None:
    transcript = (
        "Elaine Tan can be reached at elaine@example.com. "
        "Reliever inhaler used daily this week."
    )
    preview = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest/preview",
        headers=headers(),
        json={"transcript": transcript},
    )
    assert preview.status_code == 200
    assert preview.json()["redacted_phi_types"] == ["email", "name"]
    assert "Elaine Tan" not in preview.json()["redacted_text"]

    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter(
        response=successful_extraction()
    )
    ingested = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json={
            "title": "Patient session ingest",
            "source_id": "session-integration-001",
            "interaction_type": "ai_patient_session_summary",
            "transcript": transcript,
        },
    )
    assert ingested.status_code == 201
    result = ingested.json()
    record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers()
    ).json()
    entry = next(item for item in record["timeline_entries"] if item["id"] == result["entry"]["id"])
    highlight = result["highlights"][0]
    pointer = highlight["provenance_pointer"]
    assert entry["author_role"] == "system"
    assert entry["source_pointer"]["source_type"] == "pasted_transcript"
    assert entry["source_pointer"]["source_id"] == "session-integration-001"
    assert entry["source_pointer"]["transcript_reference"] == f"timeline-entry:{entry['id']}"
    assert entry["content"][pointer["start_offset"] : pointer["end_offset"]] == pointer["source_quote"]


def test_fallback_does_not_flag_explicitly_negated_respiratory_symptoms() -> None:
    extraction = fallback_extract(
        "Patient is comfortable at rest and reports no severe breathlessness. "
        "Spirometry has not yet been booked."
    )
    assert len(extraction.signals) == 1
    assert extraction.signals[0].category == "unresolved"
    assert extraction.signals[0].source_snippet == "Spirometry has not yet been booked."


def test_deepseek_adapter_disables_thinking_and_limits_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self) -> bytes:
            content = successful_extraction().model_dump_json()
            return json.dumps(
                {"choices": [{"message": {"content": content}}]}
            ).encode()

    def fake_urlopen(http_request, timeout):
        captured["payload"] = json.loads(http_request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.services.ai_ingest.request.urlopen", fake_urlopen)
    adapter = DeepSeekAdapter(
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="test-key",
        timeout=30,
        max_tokens=1_200,
    )
    result = adapter.extract("Reliever inhaler used daily this week.")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 1_200
    assert captured["timeout"] == 30
    assert result.summary == "Reliever use increased."


def test_duplicate_interaction_source_is_rejected_without_new_records(
    repository: MemoryRepository,
) -> None:
    adapter = MockLLMAdapter(response=successful_extraction())
    app.dependency_overrides[get_llm_adapter] = lambda: adapter
    body = {
        "title": "Idempotent ingest",
        "source_id": "session-idempotent-001",
        "interaction_type": "ai_doctor_consult_summary",
        "transcript": "Reliever inhaler used daily this week.",
    }

    first = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest", headers=headers(), json=body
    )
    before_duplicate = repository.get_patient_record(PATIENT_ID)
    second = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest", headers=headers(), json=body
    )
    after_duplicate = repository.get_patient_record(PATIENT_ID)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "This interaction source has already been ingested"
    assert before_duplicate is not None and after_duplicate is not None
    assert len(after_duplicate.timeline_entries) == len(before_duplicate.timeline_entries)
    assert len(after_duplicate.highlights) == len(before_duplicate.highlights)
    assert len(adapter.received_transcripts) == 1


def test_glance_is_paginated_and_ranked_by_importance_after_ingest(
    repository: MemoryRepository,
) -> None:
    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter(
        response=successful_extraction()
    )
    response = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json={
            "title": "Glance limit ingest",
            "source_id": "session-glance-limit-001",
            "interaction_type": "ai_doctor_consult_summary",
            "transcript": "Reliever inhaler used daily this week.",
        },
    )
    assert response.status_code == 201

    record = client.get(
        f"/api/patients/{PATIENT_ID}/record?highlight_page_size=2", headers=headers()
    ).json()
    assert len(record["highlights"]) == 2
    assert [item["importance_score"] for item in record["highlights"]] == [100, 98]
    assert record["highlight_pagination"] == {
        "page": 1,
        "page_size": 2,
        "total_items": 4,
        "total_pages": 2,
    }

    second_page = client.get(
        f"/api/patients/{PATIENT_ID}/record?highlight_page=2&highlight_page_size=2",
        headers=headers(),
    ).json()
    assert [item["importance_score"] for item in second_page["highlights"]] == [86, 43]
    assert second_page["highlight_pagination"]["page"] == 2


def test_singapore_name_and_local_phone_failure_case_is_fully_redacted(
    repository: MemoryRepository,
) -> None:
    transcript = (
        "Patient: My name is Tan Mei Ling, NRIC S1234567D, phone 9123 4567, "
        "email tan.meiling@example.com. "
        "Patient: I came in because my cough has lasted for 3 weeks and got worse last night. "
        "Patient: I feel short of breath when walking upstairs. "
        "Doctor: She was previously on amlodipine 5mg daily, but today we will increase it "
        "to 10mg daily because home BP remains high. Patient: I am allergic to penicillin. "
        "Doctor: Please arrange a chest X-ray and follow up with the nurse in 3 days. "
        "Nurse: Patient also mentioned she missed two doses of her blood pressure medication this week."
    )
    extraction = AIExtraction(
        title="Exertional breathlessness",
        summary="Respiratory symptoms require review.",
        signals=[
            AISignal(
                text="Shortness of breath on exertion",
                category="worsening",
                risk_level="high",
                risk_reason="New exertional breathlessness needs clinical review.",
                importance_score=93,
                extraction_confidence="high",
                confidence_reason="The symptom is explicitly stated in the source.",
                source_snippet="Patient: I feel short of breath when walking upstairs.",
            )
        ],
    )
    adapter = MockLLMAdapter(response=extraction)
    app.dependency_overrides[get_llm_adapter] = lambda: adapter

    preview = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest/preview",
        headers=headers(),
        json={"transcript": transcript},
    )
    assert preview.status_code == 200
    sanitized = preview.json()["redacted_text"]
    assert set(preview.json()["redacted_phi_types"]) == {
        "email",
        "id",
        "name",
        "phone",
    }
    for raw_phi in (
        "Tan Mei Ling",
        "S1234567D",
        "9123 4567",
        "tan.meiling@example.com",
    ):
        assert raw_phi not in sanitized
    assert "[REDACTED_NAME]" in sanitized
    assert "[REDACTED_PHONE]" in sanitized
    assert "amlodipine 5mg" in sanitized
    assert "10mg daily" in sanitized

    ingested = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json={
            "title": "PHI regression case",
            "source_id": "session-phi-regression-001",
            "interaction_type": "ai_doctor_consult_summary",
            "transcript": transcript,
        },
    )
    assert ingested.status_code == 201
    assert adapter.received_transcripts == [sanitized]
    for raw_phi in ("Tan Mei Ling", "S1234567D", "9123 4567", "tan.meiling@example.com"):
        assert raw_phi not in adapter.received_transcripts[0]


@pytest.mark.parametrize(
    "phone",
    ["9123 4567", "91234567", "+65 9123 4567", "9123-4567"],
)
def test_common_singapore_phone_formats_are_redacted(
    repository: MemoryRepository, phone: str
) -> None:
    preview = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest/preview",
        headers=headers(),
        json={"transcript": f"Please call me at {phone} tomorrow."},
    )
    assert preview.status_code == 200
    assert phone not in preview.json()["redacted_text"]
    assert "[REDACTED_PHONE]" in preview.json()["redacted_text"]
