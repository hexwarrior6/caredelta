from datetime import datetime, timezone

from app.models import (
    AuditLog,
    AuthorRole,
    Comment,
    Conflict,
    Highlight,
    InteractionEvent,
    Patient,
    PatientRecord,
    ProvenanceConfidence,
    ProvenancePointer,
    RiskLevel,
    SignalCategory,
    Task,
    TimelineEntry,
    TrustStatus,
    UserRole,
    Version,
    VisibilityScope,
)

PATIENT_ID = "patient-syn-001"
CLINIC_ID = "clinic-syn-orchard"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _provenance(
    pointer_id: str,
    entry: TimelineEntry,
    quote: str,
    source_type: str,
    source_id: str,
) -> ProvenancePointer:
    start = entry.content.index(quote)
    return ProvenancePointer(
        id=pointer_id,
        patient_id=PATIENT_ID,
        entry_id=entry.id,
        source_type=source_type,
        source_id=source_id,
        source_quote=quote,
        start_offset=start,
        end_offset=start + len(quote),
        offset_confidence=ProvenanceConfidence.HIGH,
    )


def build_seed_record() -> PatientRecord:
    april_entry = TimelineEntry(
        id="entry-2025-04-15",
        patient_id=PATIENT_ID,
        clinic_id=CLINIC_ID,
        author_role=AuthorRole.CLINICIAN,
        author_id="clinician-syn-lim",
        author_name="Dr. Maya Lim",
        timestamp=_dt("2025-04-15T02:30:00"),
        entry_type="clinician_note",
        title="Baseline asthma review",
        content=(
            "Asthma symptoms remain mild and exercise-related. Salbutamol is used "
            "about once weekly. Patient reports a penicillin allergy documented in "
            "childhood; reaction details are unclear."
        ),
        visibility_scope=VisibilityScope.CLINICIAN,
        version=1,
        source_label="Clinician-authored note",
    )
    february_entry = TimelineEntry(
        id="entry-2026-02-06",
        patient_id=PATIENT_ID,
        clinic_id=CLINIC_ID,
        author_role=AuthorRole.SYSTEM,
        author_id="system-ai-scribe",
        author_name="AI Scribe",
        timestamp=_dt("2026-02-06T08:10:00"),
        entry_type="ai_doctor_consult_summary",
        title="Doctor consult — AI-scribed summary",
        content=(
            "Patient describes night-time wheeze on three evenings this week and is "
            "using the reliever inhaler daily. No fever was reported. The patient "
            "believes she previously tolerated amoxicillin, which conflicts with the "
            "documented penicillin allergy. Clinician review is required before any "
            "allergy record change."
        ),
        visibility_scope=VisibilityScope.CLINICIAN,
        version=2,
        source_label="Synthetic transcript · session syn-260206",
    )
    august_entry = TimelineEntry(
        id="entry-2026-08-27",
        patient_id=PATIENT_ID,
        clinic_id=CLINIC_ID,
        author_role=AuthorRole.STAFF,
        author_id="staff-syn-chen",
        author_name="Alicia Chen",
        timestamp=_dt("2026-08-27T01:20:00"),
        entry_type="staff_note",
        title="Follow-up coordination",
        content=(
            "Spirometry has not yet been booked. Patient is available Tuesday "
            "afternoon and asked for a reminder by phone. Escalated to the care team "
            "because daily reliever use remains unresolved."
        ),
        visibility_scope=VisibilityScope.CARE_TEAM,
        version=1,
        source_label="Staff-authored note",
    )
    patient_entry = TimelineEntry(
        id="entry-2026-08-26-patient",
        patient_id=PATIENT_ID,
        clinic_id=CLINIC_ID,
        author_role=AuthorRole.PATIENT,
        author_id="patient-syn-001",
        author_name="Elaine Tan (synthetic)",
        timestamp=_dt("2026-08-26T12:05:00"),
        entry_type="patient_session_summary",
        title="Patient check-in",
        content=(
            "Breathing is comfortable at rest, but stairs still trigger wheeze. "
            "Reliever inhaler used five days this week. No urgent symptoms reported."
        ),
        visibility_scope=VisibilityScope.CARE_TEAM,
        version=1,
        source_label="Synthetic patient session",
    )
    instruction_entry = TimelineEntry(
        id="entry-2026-08-27-instructions",
        patient_id=PATIENT_ID,
        clinic_id=CLINIC_ID,
        author_role=AuthorRole.CLINICIAN,
        author_id="clinician-syn-lim",
        author_name="Dr. Maya Lim",
        timestamp=_dt("2026-08-27T02:05:00"),
        entry_type="patient_instruction",
        title="Approved patient instructions",
        content=(
            "Continue the current inhalers as prescribed. Seek urgent care for "
            "severe breathlessness, difficulty speaking, or symptoms not relieved "
            "by the reliever inhaler. The clinic will contact you about spirometry."
        ),
        visibility_scope=VisibilityScope.PATIENT,
        version=1,
        source_label="Clinician-approved patient instruction",
    )

    timeline = [
        instruction_entry,
        august_entry,
        patient_entry,
        february_entry,
        april_entry,
    ]
    daily_use = _provenance(
        "prov-daily-reliever",
        patient_entry,
        "Reliever inhaler used five days this week.",
        "patient_session",
        "session-syn-260826",
    )
    booking = _provenance(
        "prov-spirometry",
        august_entry,
        "Spirometry has not yet been booked.",
        "staff_note",
        august_entry.id,
    )
    allergy = _provenance(
        "prov-allergy-conflict",
        february_entry,
        "previously tolerated amoxicillin, which conflicts with the documented penicillin allergy",
        "ai_scribed_note",
        "session-syn-260206",
    )

    return PatientRecord(
        patient=Patient(
            id=PATIENT_ID,
            clinic_id=CLINIC_ID,
            display_name="Elaine Tan",
            age=42,
            pronouns="she/her",
            synthetic=True,
            summary="Asthma follow-up with worsening reliever use and an allergy discrepancy requiring review.",
            active_conditions=["Asthma"],
            allergies=["Penicillin — reaction unverified"],
            last_visit_at=_dt("2026-08-27T01:20:00"),
        ),
        highlights=[
            Highlight(
                id="highlight-reliever",
                patient_id=PATIENT_ID,
                text="Reliever use increased to five days this week",
                category=SignalCategory.WORSENING,
                risk_level=RiskLevel.HIGH,
                risk_reason="Frequent reliever use can indicate reduced asthma control.",
                trust_status=TrustStatus.NEEDS_REVIEW,
                importance_score=94,
                provenance_pointer=daily_use,
                created_at=_dt("2026-08-27T01:30:00"),
            ),
            Highlight(
                id="highlight-spirometry",
                patient_id=PATIENT_ID,
                text="Spirometry booking remains open",
                category=SignalCategory.UNRESOLVED,
                risk_level=RiskLevel.MEDIUM,
                risk_reason="Objective assessment is still outstanding after symptom escalation.",
                trust_status=TrustStatus.CLINICIAN_CONFIRMED,
                importance_score=86,
                provenance_pointer=booking,
                created_at=_dt("2026-08-27T01:31:00"),
            ),
            Highlight(
                id="highlight-allergy",
                patient_id=PATIENT_ID,
                text="Penicillin allergy history is contradictory",
                category=SignalCategory.CONTRADICTED,
                risk_level=RiskLevel.HIGH,
                risk_reason="Medication safety depends on clinician reconciliation before changing the record.",
                trust_status=TrustStatus.NEEDS_REVIEW,
                importance_score=91,
                provenance_pointer=allergy,
                created_at=_dt("2026-02-06T08:15:00"),
            ),
        ],
        tasks=[
            Task(
                id="task-spirometry",
                patient_id=PATIENT_ID,
                title="Book spirometry and confirm appointment",
                status="open",
                priority=RiskLevel.MEDIUM,
                assigned_role=AuthorRole.STAFF,
                due_at=_dt("2026-08-28T09:00:00"),
                source_entry_id=august_entry.id,
            ),
            Task(
                id="task-allergy-review",
                patient_id=PATIENT_ID,
                title="Reconcile penicillin allergy history",
                status="open",
                priority=RiskLevel.HIGH,
                assigned_role=AuthorRole.CLINICIAN,
                due_at=_dt("2026-08-28T02:00:00"),
                source_entry_id=february_entry.id,
            ),
        ],
        timeline_entries=timeline,
        comments=[
            Comment(
                id="comment-001",
                patient_id=PATIENT_ID,
                entry_id=august_entry.id,
                author_role=AuthorRole.STAFF,
                author_id="staff-syn-chen",
                author_name="Alicia Chen",
                body="@DrLim Please review whether an earlier clinical assessment is needed.",
                created_at=_dt("2026-08-27T01:24:00"),
                resolved=False,
                mentions=["clinician-syn-lim"],
                assigned_role=UserRole.CLINICIAN,
            )
        ],
        versions=[
            Version(
                id="version-april-001",
                patient_id=PATIENT_ID,
                entry_id=april_entry.id,
                version_number=1,
                content_snapshot=april_entry.content,
                changed_by=april_entry.author_id,
                changed_by_role=april_entry.author_role,
                created_at=april_entry.timestamp,
                change_summary="Clinician note created",
            ),
            Version(
                id="version-august-001",
                patient_id=PATIENT_ID,
                entry_id=august_entry.id,
                version_number=1,
                content_snapshot=august_entry.content,
                changed_by=august_entry.author_id,
                changed_by_role=august_entry.author_role,
                created_at=august_entry.timestamp,
                change_summary="Staff note created",
            ),
            Version(
                id="version-feb-001",
                patient_id=PATIENT_ID,
                entry_id=february_entry.id,
                version_number=1,
                content_snapshot="Initial synthetic AI consult summary pending clinician review.",
                changed_by="system-ai-scribe",
                changed_by_role=AuthorRole.SYSTEM,
                created_at=_dt("2026-02-06T08:10:00"),
                change_summary="AI-scribed entry created",
            ),
            Version(
                id="version-feb-002",
                patient_id=PATIENT_ID,
                entry_id=february_entry.id,
                version_number=2,
                content_snapshot=february_entry.content,
                changed_by="clinician-syn-lim",
                changed_by_role=AuthorRole.CLINICIAN,
                created_at=_dt("2026-02-06T08:22:00"),
                change_summary="Added explicit allergy review safety instruction",
            ),
        ],
        audit_logs=[
            AuditLog(
                id="audit-001",
                patient_id=PATIENT_ID,
                actor_id="clinician-syn-lim",
                actor_role=AuthorRole.CLINICIAN,
                action="update_entry",
                entity_type="timeline_entry",
                entity_id=february_entry.id,
                changed_fields=["content", "version"],
                created_at=_dt("2026-02-06T08:22:00"),
                request_id="request-syn-001",
            )
        ],
        interaction_events=[
            InteractionEvent(
                id="interaction-001",
                patient_id=PATIENT_ID,
                actor_id="clinician-syn-lim",
                actor_role=AuthorRole.CLINICIAN,
                event_type="pin_highlight",
                highlight_id="highlight-reliever",
                extracted_topic="asthma_reliever_frequency",
                weight_delta=0.15,
                created_at=_dt("2026-08-27T01:35:00"),
            )
        ],
        conflicts=[
            Conflict(
                id="conflict-allergy-001",
                patient_id=PATIENT_ID,
                conflict_type="allergy",
                summary="Historical penicillin allergy conflicts with reported amoxicillin tolerance.",
                severity=RiskLevel.HIGH,
                status="open",
                source_entry_ids=[april_entry.id, february_entry.id],
                detected_at=_dt("2026-02-06T08:15:00"),
            )
        ],
        generated_at=_dt("2026-08-27T02:00:00"),
    )
