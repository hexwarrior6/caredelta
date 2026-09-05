import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.main import app
from app.repositories import MemoryRepository
from app.seed import CLINIC_ID, PATIENT_ID, build_seed_record


client = TestClient(app)


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


def test_clinician_accepts_suggestion_and_patient_sees_safe_confirmed_signal(
    isolated_repository: MemoryRepository,
) -> None:
    patient_before = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers("patient", PATIENT_ID),
    ).json()
    assert "highlight-reliever" not in {
        item["id"] for item in patient_before["highlights"]
    }

    response = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-reliever/decision",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"decision": "accept", "reason": "Source confirms the reported change."},
    )

    assert response.status_code == 200
    accepted = response.json()
    assert accepted["trust_status"] == "clinician_confirmed"
    assert accepted["abstained_from_glance"] is False
    assert accepted["abstention_reason"] is None
    assert accepted["reviewed_by"] == "clinician-syn-lim"
    assert accepted["reviewed_by_role"] == "clinician"
    assert accepted["reviewed_at"]
    assert accepted["review_reason"] == "Source confirms the reported change."

    patient_after = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers("patient", PATIENT_ID),
    ).json()
    assert "highlight-reliever" in {
        item["id"] for item in patient_after["highlights"]
    }

    stored = isolated_repository.get_patient_record(PATIENT_ID)
    assert stored is not None
    audit = stored.audit_logs[-1]
    assert audit.action == "accept_highlight"
    assert audit.actor_id == "clinician-syn-lim"
    assert audit.entity_type == "highlight"
    assert audit.entity_id == "highlight-reliever"
    assert set(audit.changed_fields) == {
        "trust_status",
        "reviewed_by",
        "reviewed_by_role",
        "reviewed_at",
        "review_reason",
    }
    assert not hasattr(audit, "content")


def test_rejected_signal_leaves_glance_and_review_queue(
    isolated_repository: MemoryRepository,
) -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-allergy/decision",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"decision": "reject", "reason": "Duplicate conflict candidate."},
    )

    assert response.status_code == 200
    rejected = response.json()
    assert rejected["trust_status"] == "rejected"
    assert rejected["abstained_from_glance"] is True
    assert rejected["abstention_reason"] == "Rejected by clinical review."
    assert rejected["review_reason"] == "Duplicate conflict candidate."

    record = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers("clinician", "clinician-syn-lim"),
    ).json()
    assert "highlight-allergy" not in {item["id"] for item in record["highlights"]}
    assert "highlight-allergy" not in {
        item["id"] for item in record["review_queue"]
    }

    stored = isolated_repository.get_patient_record(PATIENT_ID)
    assert stored is not None
    assert stored.audit_logs[-1].action == "reject_highlight"


@pytest.mark.parametrize(
    ("role", "actor_id"),
    [("patient", PATIENT_ID), ("staff", "staff-syn-chen")],
)
def test_patient_and_staff_cannot_decide_highlights(role: str, actor_id: str) -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-reliever/decision",
        headers=headers(role, actor_id),
        json={"decision": "accept"},
    )

    assert response.status_code == 403


def test_highlight_decision_enforces_clinic_scope() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-reliever/decision",
        headers=headers("clinician", "clinician-syn-lim", "clinic-syn-other"),
        json={"decision": "accept"},
    )

    assert response.status_code == 404


def test_admin_can_reverse_a_rejection_and_default_reason_is_recorded() -> None:
    reject = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-reliever/decision",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"decision": "reject"},
    )
    accept = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-reliever/decision",
        headers=headers("admin", "admin-syn-morgan"),
        json={"decision": "accept", "reason": "   "},
    )

    assert reject.status_code == 200
    assert accept.status_code == 200
    accepted = accept.json()
    assert accepted["trust_status"] == "clinician_confirmed"
    assert accepted["reviewed_by"] == "admin-syn-morgan"
    assert accepted["reviewed_by_role"] == "admin"
    assert accepted["review_reason"] == "Accepted after clinical source review."


def test_accept_does_not_bypass_source_visibility_for_raw_ai_note() -> None:
    response = client.post(
        f"/api/patients/{PATIENT_ID}/highlights/highlight-allergy/decision",
        headers=headers("clinician", "clinician-syn-lim"),
        json={"decision": "accept"},
    )
    assert response.status_code == 200

    patient_record = client.get(
        f"/api/patients/{PATIENT_ID}/record",
        headers=headers("patient", PATIENT_ID),
    ).json()
    assert "highlight-allergy" not in {
        item["id"] for item in patient_record["highlights"]
    }
