from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_adapter, get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record
from app.services.ai_ingest import AIExtraction, AISignal, MockLLMAdapter
from app.services.self_learning import MAX_LEARNING_BOOST, apply_bounded_learning


client = TestClient(app)


def headers(role: str = "clinician", actor: str = "clinician-syn-lim") -> dict[str, str]:
    return {
        "X-Actor-Id": actor,
        "X-Actor-Role": role,
        "X-Clinic-Id": CLINIC_ID,
    }


@pytest.fixture
def repository():
    isolated = MemoryRepository([build_seed_record()])
    app.dependency_overrides[get_repository] = lambda: isolated
    yield isolated
    app.dependency_overrides.clear()


def test_prior_pins_apply_explained_bounded_learning_boost(
    repository: MemoryRepository,
) -> None:
    for _ in range(5):
        response = client.post(
            f"/api/patients/{PATIENT_ID}/highlights/highlight-spirometry/interactions",
            headers=headers(),
            json={"event_type": "pin"},
        )
        assert response.status_code == 201

    record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers()
    ).json()
    signal = next(item for item in record["highlights"] if item["id"] == "highlight-spirometry")
    assert signal["learning_adjustment"] == MAX_LEARNING_BOOST
    assert signal["learning_reason"] == "boosted_by_prior_pins"
    assert signal["importance_score"] == min(
        100, signal["base_importance_score"] + MAX_LEARNING_BOOST
    )


def test_pin_changes_only_the_clicked_card(repository: MemoryRepository) -> None:
    before = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers(),
    ).json()
    before_scores = {item["id"]: item["importance_score"] for item in before["highlights"]}

    response = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-spirometry/interactions",
        headers=headers(),
        json={"event_type": "pin"},
    )
    assert response.status_code == 201
    after = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers(),
    ).json()
    after_scores = {item["id"]: item["importance_score"] for item in after["highlights"]}

    assert after_scores["highlight-spirometry"] == before_scores["highlight-spirometry"] + 4
    assert after_scores["highlight-reliever"] == before_scores["highlight-reliever"]
    assert after_scores["highlight-baseline-history"] == before_scores["highlight-baseline-history"]


def test_less_relevant_feedback_reduces_only_non_safety_signal(
    repository: MemoryRepository,
) -> None:
    reduced = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-baseline-history/interactions",
        headers=headers(),
        json={"event_type": "less_relevant"},
    )
    protected = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-allergy/interactions",
        headers=headers(),
        json={"event_type": "less_relevant"},
    )
    assert reduced.status_code == 201
    assert protected.status_code == 201

    record = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers(),
    ).json()
    historical = next(
        item for item in record["highlights"] if item["id"] == "highlight-baseline-history"
    )
    allergy = next(
        item for item in record["review_queue"] if item["id"] == "highlight-allergy"
    )
    assert historical["learning_adjustment"] == -2
    assert historical["learning_reason"] == "reduced_by_less_relevant_feedback"
    assert allergy["learning_adjustment"] == 0
    assert "safety_protected_from_negative_learning" in allergy["learning_reason"]


def test_positive_and_negative_feedback_share_one_net_adjustment(
    repository: MemoryRepository,
) -> None:
    endpoint = (
        f"/api/patients/{PATIENT_ID}/highlights/"
        "highlight-baseline-history/interactions"
    )
    pinned = client.post(endpoint, headers=headers(), json={"event_type": "pin"})
    reduced = client.post(
        endpoint,
        headers=headers(),
        json={"event_type": "less_relevant"},
    )
    assert pinned.status_code == 201
    assert reduced.status_code == 201

    record = client.get(
        f"/api/patients/{PATIENT_ID}/record", headers=headers()
    ).json()
    signal = next(
        item for item in record["highlights"] if item["id"] == "highlight-baseline-history"
    )
    assert signal["learning_adjustment"] == 2
    assert signal["importance_score"] == 55 + 2 - 12
    assert signal["learning_reason"] == (
        "boosted_by_prior_pins, reduced_by_less_relevant_feedback"
    )


def test_safety_signal_never_receives_age_downgrade() -> None:
    allergy = next(
        item for item in build_seed_record().highlights if item.id == "highlight-allergy"
    )
    evaluated = apply_bounded_learning(
        allergy,
        [],
        now=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    assert evaluated.decay_adjustment == 0
    assert evaluated.importance_score >= allergy.importance_score
    assert evaluated.decay_reason == "Safety-protected signal: age decay is not applied."


def test_old_non_safety_seed_signal_has_explained_data_decay(
    repository: MemoryRepository,
) -> None:
    record = client.get(
        f"/api/patients/{PATIENT_ID}/record?highlight_page=2&highlight_page_size=3",
        headers=headers(),
    ).json()
    historical = next(
        item for item in record["highlights"] if item["id"] == "highlight-baseline-history"
    )
    assert historical["base_importance_score"] == 55
    assert historical["decay_adjustment"] == -12
    assert "summarized historical signal" in historical["decay_reason"]


def test_comment_edit_and_highlight_events_are_recorded(
    repository: MemoryRepository,
) -> None:
    viewed = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-reliever/interactions",
        headers=headers(),
        json={"event_type": "highlight"},
    )
    assert viewed.status_code == 201

    commented = client.post(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27/comments",
        headers=headers("staff", "staff-syn-chen"),
        json={"body": "Please review this outstanding action."},
    )
    assert commented.status_code == 201

    edited = client.patch(
        f"/api/patients/{PATIENT_ID}/entries/entry-2026-08-27",
        headers=headers("staff", "staff-syn-chen"),
        json={
            "content": "Spirometry remains unbooked; patient availability reconfirmed.",
            "expected_version": 1,
        },
    )
    assert edited.status_code == 200

    stored = repository.get_patient_record(PATIENT_ID)
    assert stored is not None
    event_types = {event.event_type for event in stored.interaction_events}
    assert {"pin", "highlight", "comment", "edit"} <= event_types


@pytest.mark.parametrize(
    ("source_id", "text", "category", "conflict_type"),
    [
        (
            "conflict-allergy",
            "Patient denies the documented penicillin allergy, creating an allergy conflict.",
            "contradicted",
            "allergy",
        ),
        (
            "conflict-medication",
            "Amlodipine dose is 10mg, contradicting the medication record.",
            "contradicted",
            "medication",
        ),
        (
            "conflict-task",
            "Spirometry booking is still pending and not yet arranged.",
            "unresolved",
            "task",
        ),
    ],
)
def test_ingest_detects_two_source_conflicts(
    repository: MemoryRepository,
    source_id: str,
    text: str,
    category: str,
    conflict_type: str,
) -> None:
    extraction = AIExtraction(
        title="Conflict detected",
        summary="One source-backed conflict needs review.",
        signals=[
            AISignal(
                text=text,
                category=category,
                risk_level="medium",
                risk_reason=text,
                importance_score=80,
                extraction_confidence="high",
                confidence_reason="The conflicting statement is explicit.",
                source_snippet=text,
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
            "source_id": source_id,
            "interaction_type": "ai_doctor_consult_summary",
            "transcript": text,
        },
    )

    assert response.status_code == 201
    conflict = next(
        item for item in response.json()["conflicts"] if item["conflict_type"] == conflict_type
    )
    assert conflict["status"] == "open"
    assert len(conflict["source_entry_ids"]) == 2
    assert response.json()["entry"]["id"] in conflict["source_entry_ids"]
