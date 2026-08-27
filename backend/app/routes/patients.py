from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import (
    Action,
    get_auth_context,
    require_action,
    require_clinic_scope,
)
from app.dependencies import get_llm_adapter, get_repository
from app.models import (
    AuditLog,
    AIIngestRequest,
    AIIngestResponse,
    AIRedactionPreviewRequest,
    AIRedactionPreviewResponse,
    AuthContext,
    AuthorRole,
    Comment,
    CreateCommentRequest,
    CreateEntryRequest,
    PatientRecord,
    Highlight,
    ProvenanceConfidence,
    ProvenancePointer,
    RevertEntryRequest,
    TimelineEntry,
    TrustStatus,
    UpdateEntryRequest,
    UpdateCommentStatusRequest,
    UserRole,
    Version,
    VisibilityScope,
)
from app.repositories import PatientRecordRepository, VersionConflictError
from app.services.patient_records import entry_action, filter_patient_record
from app.services.ai_ingest import LLMAdapter, extract_with_fallback, redact_phi

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.post(
    "/{patient_id}/ai-ingest/preview",
    response_model=AIRedactionPreviewResponse,
)
def preview_ai_ingest_redaction(
    patient_id: str,
    payload: AIRedactionPreviewRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AIRedactionPreviewResponse:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.INGEST_AI_NOTE)

    redaction = redact_phi(payload.transcript, record.patient.display_name)
    return AIRedactionPreviewResponse(
        redacted_text=redaction.text,
        redacted_phi_types=redaction.redacted_phi_types,
        warning=(
            None
            if redaction.redacted_phi_types
            else "No supported PHI pattern was detected; review the preview before ingest."
        ),
    )


@router.post(
    "/{patient_id}/ai-ingest",
    response_model=AIIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_ai_scribed_note(
    patient_id: str,
    payload: AIIngestRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    adapter: Annotated[LLMAdapter | None, Depends(get_llm_adapter)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AIIngestResponse:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.INGEST_AI_NOTE)

    ingest_key = f"{payload.interaction_type}:{payload.source_id}"
    if any(
        f"{highlight.provenance_pointer.source_type}:{highlight.provenance_pointer.source_id}"
        == ingest_key
        for highlight in record.highlights
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This interaction source has already been ingested",
        )

    redaction = redact_phi(payload.transcript, record.patient.display_name)
    extraction, method, fallback_reason = extract_with_fallback(adapter, redaction.text)
    now = datetime.now(timezone.utc)
    entry = TimelineEntry(
        id=f"entry-{uuid4()}",
        patient_id=patient_id,
        clinic_id=record.patient.clinic_id,
        author_role=AuthorRole.SYSTEM,
        author_id="system-ai-scribe",
        author_name="AI Scribe",
        timestamp=now,
        entry_type=payload.interaction_type,
        title=extraction.title,
        content=redaction.text,
        visibility_scope=VisibilityScope.CLINICIAN,
        version=1,
        source_label=f"{payload.interaction_type} · {payload.source_id}",
    )
    highlights: list[Highlight] = []
    for signal in extraction.signals:
        start = entry.content.index(signal.source_snippet)
        highlights.append(
            Highlight(
                id=f"highlight-{uuid4()}",
                patient_id=patient_id,
                text=signal.text,
                category=signal.category,
                risk_level=signal.risk_level,
                risk_reason=signal.risk_reason,
                trust_status=TrustStatus.AI_SUGGESTED,
                importance_score=signal.importance_score,
                provenance_pointer=ProvenancePointer(
                    id=f"provenance-{uuid4()}",
                    patient_id=patient_id,
                    entry_id=entry.id,
                    source_type=payload.interaction_type,
                    source_id=payload.source_id,
                    source_quote=signal.source_snippet,
                    start_offset=start,
                    end_offset=start + len(signal.source_snippet),
                    offset_confidence=ProvenanceConfidence.HIGH,
                ),
                created_at=now,
            )
        )
    version = Version(
        id=f"version-{uuid4()}",
        patient_id=patient_id,
        entry_id=entry.id,
        version_number=1,
        content_snapshot=entry.content,
        changed_by="system-ai-scribe",
        changed_by_role=AuthorRole.SYSTEM,
        created_at=now,
        change_summary="AI-scribed note ingested after PHI redaction",
    )
    audit_log = AuditLog(
        id=f"audit-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        action="ai_ingest",
        entity_type="timeline_entry",
        entity_id=entry.id,
        changed_fields=["entry", "highlights", "redaction_metadata"],
        created_at=now,
        request_id=f"request-{uuid4()}",
    )
    inserted = repository.add_ai_ingest(
        ingest_key, entry, highlights, version, audit_log
    )
    if not inserted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This interaction source has already been ingested",
        )
    return AIIngestResponse(
        entry=entry,
        highlights=highlights,
        extraction_method=method,
        fallback_reason=fallback_reason,
        summary=extraction.summary,
        redacted_phi_types=redaction.redacted_phi_types,
    )


def require_entry_edit(context: AuthContext, entry: TimelineEntry) -> None:
    if entry.entry_type == "staff_note":
        require_action(context, Action.EDIT_STAFF_NOTE)
        if context.role == UserRole.STAFF and entry.author_id != context.actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff can edit only their own staff notes",
            )
        return
    if entry.entry_type in {"clinician_note", "clinician_section"}:
        require_action(context, Action.EDIT_CLINICIAN_SECTION)
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This entry type is immutable through the note editor",
    )


def revision_metadata(
    *,
    patient_id: str,
    entry: TimelineEntry,
    content: str,
    context: AuthContext,
    action: str,
    summary: str,
    now: datetime,
) -> tuple[Version, AuditLog]:
    next_version = entry.version + 1
    version = Version(
        id=f"version-{uuid4()}",
        patient_id=patient_id,
        entry_id=entry.id,
        version_number=next_version,
        content_snapshot=content,
        changed_by=context.actor_id,
        changed_by_role=AuthorRole(context.role.value),
        created_at=now,
        change_summary=summary,
    )
    audit_log = AuditLog(
        id=f"audit-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        action=action,
        entity_type="timeline_entry",
        entity_id=entry.id,
        changed_fields=["content", "version"],
        created_at=now,
        request_id=f"request-{uuid4()}",
    )
    return version, audit_log


@router.get("/{patient_id}/record", response_model=PatientRecord)
def get_patient_record(
    patient_id: str,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
    highlight_page: Annotated[int, Query(ge=1)] = 1,
    highlight_page_size: Annotated[int, Query(ge=1, le=6)] = 3,
) -> PatientRecord:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient record not found",
        )
    require_action(context, Action.READ_PATIENT_SUMMARY)
    return filter_patient_record(
        record,
        context,
        highlight_page=highlight_page,
        highlight_page_size=highlight_page_size,
    )


@router.post(
    "/{patient_id}/entries",
    response_model=TimelineEntry,
    status_code=status.HTTP_201_CREATED,
)
def create_timeline_entry(
    patient_id: str,
    payload: CreateEntryRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> TimelineEntry:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)

    action = (
        Action.CREATE_STAFF_NOTE
        if payload.section == "staff_note"
        else Action.EDIT_CLINICIAN_SECTION
    )
    require_action(context, action)

    author_role = (
        AuthorRole.STAFF
        if payload.section == "staff_note" and context.role != UserRole.ADMIN
        else AuthorRole.CLINICIAN
        if payload.section == "clinician_section" and context.role != UserRole.ADMIN
        else AuthorRole.ADMIN
    )
    now = datetime.now(timezone.utc)
    entry = TimelineEntry(
        id=f"entry-{uuid4()}",
        patient_id=patient_id,
        clinic_id=context.clinic_id,
        author_role=author_role,
        author_id=context.actor_id,
        author_name=f"Demo {context.role.value.title()}",
        timestamp=now,
        entry_type=payload.section,
        title=payload.title,
        content=payload.content,
        visibility_scope=(
            VisibilityScope.CARE_TEAM
            if payload.section == "staff_note"
            else VisibilityScope.CLINICIAN
        ),
        version=1,
        source_label=f"{context.role.value.title()}-authored note",
    )
    version = Version(
        id=f"version-{uuid4()}",
        patient_id=patient_id,
        entry_id=entry.id,
        version_number=1,
        content_snapshot=entry.content,
        changed_by=context.actor_id,
        changed_by_role=entry.author_role,
        created_at=now,
        change_summary="Timeline entry created",
    )
    audit_log = AuditLog(
        id=f"audit-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        action="create_entry",
        entity_type="timeline_entry",
        entity_id=entry.id,
        changed_fields=["title", "content", "version"],
        created_at=now,
        request_id=f"request-{uuid4()}",
    )
    return repository.add_timeline_entry(entry, version, audit_log)


@router.post(
    "/{patient_id}/entries/{entry_id}/comments",
    response_model=Comment,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    patient_id: str,
    entry_id: str,
    payload: CreateCommentRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> Comment:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.CREATE_INTERNAL_COMMENT)

    entry = next((item for item in record.timeline_entries if item.id == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    require_action(context, entry_action(entry))

    comment = Comment(
        id=f"comment-{uuid4()}",
        patient_id=patient_id,
        entry_id=entry_id,
        author_role=AuthorRole(context.role.value),
        author_id=context.actor_id,
        author_name=f"Demo {context.role.value.title()}",
        body=payload.body,
        created_at=datetime.now(timezone.utc),
        resolved=False,
        mentions=payload.mentions,
        assigned_role=payload.assigned_role,
    )
    return repository.add_comment(comment)


@router.patch(
    "/{patient_id}/comments/{comment_id}",
    response_model=Comment,
)
def update_comment_status(
    patient_id: str,
    comment_id: str,
    payload: UpdateCommentStatusRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> Comment:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.RESOLVE_INTERNAL_COMMENT)

    comment = next((item for item in record.comments if item.id == comment_id), None)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    entry = next(
        (item for item in record.timeline_entries if item.id == comment.entry_id), None
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    require_action(context, entry_action(entry))

    updated = repository.update_comment_status(patient_id, comment_id, payload.resolved)
    if updated is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return updated


@router.patch("/{patient_id}/entries/{entry_id}", response_model=TimelineEntry)
def update_timeline_entry(
    patient_id: str,
    entry_id: str,
    payload: UpdateEntryRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> TimelineEntry:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)

    entry = next((item for item in record.timeline_entries if item.id == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")

    require_entry_edit(context, entry)

    now = datetime.now(timezone.utc)
    version, audit_log = revision_metadata(
        patient_id=patient_id,
        entry=entry,
        content=payload.content,
        context=context,
        action="update_entry",
        summary="Timeline entry edited",
        now=now,
    )
    try:
        updated = repository.update_timeline_entry(
            patient_id,
            entry_id,
            payload.content,
            payload.expected_version,
            version,
            audit_log,
        )
    except VersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry version does not match expected_version",
        ) from error
    if updated is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    return updated


@router.post(
    "/{patient_id}/entries/{entry_id}/revert",
    response_model=TimelineEntry,
)
def revert_timeline_entry(
    patient_id: str,
    entry_id: str,
    payload: RevertEntryRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> TimelineEntry:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.ROLLBACK_ENTRY)

    entry = next((item for item in record.timeline_entries if item.id == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    require_entry_edit(context, entry)

    target = next(
        (
            version
            for version in record.versions
            if version.entry_id == entry_id
            and version.version_number == payload.target_version
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Target version not found")

    now = datetime.now(timezone.utc)
    version, audit_log = revision_metadata(
        patient_id=patient_id,
        entry=entry,
        content=target.content_snapshot,
        context=context,
        action="revert_entry",
        summary=f"Reverted to version {target.version_number}",
        now=now,
    )
    try:
        reverted = repository.update_timeline_entry(
            patient_id,
            entry_id,
            target.content_snapshot,
            payload.expected_version,
            version,
            audit_log,
        )
    except VersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry version does not match expected_version",
        ) from error
    if reverted is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    return reverted
