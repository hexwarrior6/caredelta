import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_adapter, get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record
from app.services.ai_ingest import AIExtraction, AISignal, MockLLMAdapter, fallback_extract
from app.services.delta_engine import evaluate_signal


client = TestClient(app)


def headers() -> dict[str, str]:
    return {
        "X-Actor-Id": "clinician-syn-lim",
        "X-Actor-Role": "clinician",
        "X-Clinic-Id": CLINIC_ID,
    }


@pytest.fixture
def repository():
    isolated = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: isolated
    yield isolated
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A new symptom was documented.", "new"),
        ("Breathing became worse today.", "worsening"),
        ("The same symptoms returned again.", "recurring"),
        ("Spirometry is still pending.", "unresolved"),
        ("This conflicts with the allergy record.", "contradicted"),
        ("The result was confirmed by the clinician.", "confirmed"),
    ],
)
def test_fallback_supports_all_delta_categories(text: str, expected: str) -> None:
    extraction = fallback_extract(text)
    if expected == "new":
        assert extraction.signals[0].category == "new"
    else:
        assert extraction.signals[0].category == expected


def test_deterministic_risk_floor_overrides_unsafe_low_risk() -> None:
    evaluation = evaluate_signal(
        text="The penicillin allergy record is contradicted.",
        category="contradicted",
        proposed_risk="low",
        extraction_confidence="high",
        provenance_confidence="high",
    )

    assert evaluation.risk_level == "high"
    assert evaluation.risk_floor_applied is True
    assert "deterministic high-risk floor" in evaluation.risk_floor_reason
    assert "High risk base" in evaluation.importance_reason


def test_low_confidence_signal_abstains_and_enters_review_queue(
    repository: MemoryRepository,
) -> None:
    transcript = "Patient mentions a vague concern without further context."
    extraction = AIExtraction(
        title="Uncertain patient concern",
        summary="One uncertain signal needs review.",
        signals=[
            AISignal(
                text=transcript,
                category="new",
                risk_level="low",
                risk_reason="The concern is insufficiently specific.",
                importance_score=80,
                extraction_confidence="low",
                confidence_reason="The statement lacks clinical detail and corroboration.",
                source_snippet=transcript,
            )
        ],
    )
    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter(
        response=extraction
    )

    response = client.post(
        f"/api/patients/{PATIENT_ID}/ai-ingest",
        headers=headers(),
        json={
            "source_id": "session-low-confidence",
            "interaction_type": "ai_patient_session_summary",
            "transcript": transcript,
        },
    )
    assert response.status_code == 201
    result = response.json()
    signal_id = result["highlights"][0]["id"]
    assert result["promoted_count"] == 0
    assert result["review_queue_count"] == 1
    assert result["highlights"][0]["abstained_from_glance"] is True

    record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers()
    ).json()
    assert signal_id not in {item["id"] for item in record["highlights"]}
    assert signal_id in {item["id"] for item in record["review_queue"]}


def test_conflicting_seed_signal_is_review_needed_not_in_glance(
    repository: MemoryRepository,
) -> None:
    record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers()
    ).json()

    allergy = next(
        item for item in record["review_queue"] if item["category"] == "contradicted"
    )
    assert allergy["trust_status"] == "needs_review"
    assert allergy["abstained_from_glance"] is True
    assert allergy["id"] not in {item["id"] for item in record["highlights"]}
    assert allergy["risk_reason"]
    assert allergy["confidence_reason"]
    assert allergy["importance_reason"]
