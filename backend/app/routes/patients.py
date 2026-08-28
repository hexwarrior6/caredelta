from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.auth import (
    Action,
    get_auth_context,
    require_action,
    require_clinic_scope,
)
from app.dependencies import get_asr_adapter, get_llm_adapter, get_repository
from app.models import (
    AuditLog,
    AIIngestRequest,
    AIIngestResponse,
    AIRedactionPreviewRequest,
    AIRedactionPreviewResponse,
    AudioTranscriptionResponse,
    AuthContext,
    AuthorRole,
    Comment,
    CreateCommentRequest,
    CreateEntryRequest,
    CreateInteractionRequest,
    CreateManualHighlightRequest,
    PatientRecord,
    PatientChatIngestResponse,
    PatientChatMessage,
    PatientChatRequest,
    PatientChatResponse,
    PatientChatSession,
    Highlight,
    HighlightDecisionRequest,
    InteractionEvent,
    ProvenanceConfidence,
    ProvenancePointer,
    RiskLevel,
    SignalCategory,
    RevertEntryRequest,
    TimelineEntry,
    UpdateEntryRequest,
    UpdateCommentStatusRequest,
    UserRole,
    TrustStatus,
    Version,
    VisibilityScope,
)
from app.repositories import PatientRecordRepository, VersionConflictError
from app.services.patient_records import entry_action, filter_patient_record
from app.services.ai_ingest import LLMAdapter, extract_with_fallback, redact_phi
from app.services.asr import ASRAdapter
from app.services.delta_engine import evaluate_signal
from app.services.conflict_detection import detect_conflicts

router = APIRouter(prefix="/api/patients", tags=["patients"])

MAX_AUDIO_BYTES = 15 * 1024 * 1024
SUPPORTED_AUDIO_TYPES = {
    "audio/aac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/vnd.wave",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "video/mp4",
}
AUDIO_FORMATS = {
    "audio/aac": "aac",
    "audio/m4a": "m4a",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/vnd.wave": "wav",
    "audio/wav": "wav",
    "audio/webm": "ogg",
    "audio/x-m4a": "m4a",
    "audio/x-wav": "wav",
    "video/mp4": "m4a",
}


def record_entry_interactions(
    repository: PatientRecordRepository,
    record: PatientRecord,
    entry_id: str,
    context: AuthContext,
    event_type: str,
) -> None:
    linked = [
        highlight
        for highlight in record.highlights
        if highlight.provenance_pointer.entry_id == entry_id
    ]
    for highlight in linked or [None]:
        repository.add_interaction_event(
            InteractionEvent(
                id=f"interaction-{uuid4()}",
                patient_id=record.patient.id,
                actor_id=context.actor_id,
                actor_role=AuthorRole(context.role.value),
                event_type=event_type,
                highlight_id=highlight.id if highlight else f"entry:{entry_id}",
                extracted_topic=highlight.category.value if highlight else "general",
                weight_delta={"comment": 2, "edit": 3}.get(event_type, 0),
                created_at=datetime.now(timezone.utc),
            )
        )


@router.post(
    "/{patient_id}/audio-transcription",
    response_model=AudioTranscriptionResponse,
)
async def transcribe_consult_audio(
    patient_id: str,
    audio: Annotated[UploadFile, File(...)],
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    adapter: Annotated[ASRAdapter | None, Depends(get_asr_adapter)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AudioTranscriptionResponse:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.TRANSCRIBE_AUDIO)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Volcengine speech recognition is unavailable")
    reported_content_type = (audio.content_type or "").lower()
    content_type = reported_content_type.split(";", 1)[0].strip()
    if content_type not in SUPPORTED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio format")
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file exceeds the 15 MB limit")
    try:
        transcript = adapter.transcribe(content, AUDIO_FORMATS[content_type])
    except Exception as error:
        raise HTTPException(status_code=502, detail="Speech recognition failed") from error
    return AudioTranscriptionResponse(
        transcript=transcript,
        engine="volcengine_bigmodel_flash",
        filename=audio.filename or "consult-audio",
        content_type=reported_content_type,
    )


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


@router.post("/{patient_id}/ai-chat", response_model=PatientChatResponse)
def chat_with_patient_assistant(
    patient_id: str,
    payload: PatientChatRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    adapter: Annotated[LLMAdapter | None, Depends(get_llm_adapter)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> PatientChatResponse:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.PATIENT_AI_CHAT)
    if adapter is None or not hasattr(adapter, "chat"):
        raise HTTPException(status_code=503, detail="DeepSeek patient assistant is unavailable")

    session = next(
        (item for item in record.patient_chat_sessions if item.id == payload.session_id),
        None,
    )
    if payload.session_id and session is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if session and session.ingested_entry_id:
        raise HTTPException(status_code=409, detail="This conversation is already in the record")

    now = datetime.now(timezone.utc)
    redaction = redact_phi(payload.message, record.patient.display_name)
    if session is None:
        session = PatientChatSession(
            id=f"patient-chat-{uuid4()}",
            patient_id=patient_id,
            title=redaction.text.strip()[:80] or "Patient AI conversation",
            created_at=now,
            updated_at=now,
        )

    llm_messages = [
        {"role": "user" if message.role == "patient" else "assistant", "content": message.content}
        for message in session.messages[-12:]
    ]
    llm_messages.append({"role": "user", "content": redaction.text})
    clinical_context = (
        f"Summary: {record.patient.summary}\n"
        f"Active conditions: {', '.join(record.patient.active_conditions)}\n"
        f"Allergies: {', '.join(record.patient.allergies)}"
    )
    try:
        answer = adapter.chat(llm_messages, clinical_context)  # type: ignore[attr-defined]
    except Exception as error:
        raise HTTPException(status_code=503, detail="DeepSeek could not answer right now") from error

    session.messages.extend(
        [
            PatientChatMessage(
                id=f"chat-message-{uuid4()}", role="patient", content=redaction.text, created_at=now
            ),
            PatientChatMessage(
                id=f"chat-message-{uuid4()}", role="assistant", content=answer, created_at=datetime.now(timezone.utc)
            ),
        ]
    )
    session.updated_at = datetime.now(timezone.utc)
    repository.save_patient_chat_session(session)
    return PatientChatResponse(session=session, redacted_phi_types=redaction.redacted_phi_types)


@router.post(
    "/{patient_id}/ai-chat/{session_id}/ingest",
    response_model=PatientChatIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_patient_chat(
    patient_id: str,
    session_id: str,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    adapter: Annotated[LLMAdapter | None, Depends(get_llm_adapter)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> PatientChatIngestResponse:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.PATIENT_AI_CHAT)
    session = next((item for item in record.patient_chat_sessions if item.id == session_id), None)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if session.ingested_entry_id:
        raise HTTPException(status_code=409, detail="This conversation is already in the record")

    transcript = "\n".join(
        f"{'Patient' if message.role == 'patient' else 'AI assistant'}: {message.content}"
        for message in session.messages
    )
    result = ingest_ai_scribed_note(
        patient_id,
        AIIngestRequest(
            transcript=transcript,
            source_id=session.id,
            interaction_type="ai_patient_session_summary",
        ),
        repository,
        adapter,
        context,
    )
    session.ingested_entry_id = result.entry.id
    session.updated_at = datetime.now(timezone.utc)
    repository.save_patient_chat_session(session)
    return PatientChatIngestResponse(**result.model_dump(), session=session)


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
    if context.role == UserRole.PATIENT and payload.interaction_type != "ai_patient_session_summary":
        raise HTTPException(
            status_code=403,
            detail="Patients may ingest only their own patient-session conversations",
        )

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
    extraction_source = redaction.text
    if context.role == UserRole.PATIENT:
        patient_lines = [
            line for line in redaction.text.splitlines() if line.startswith("Patient: ")
        ]
        extraction_source = "\n".join(patient_lines) or redaction.text
    extraction, method, fallback_reason = extract_with_fallback(adapter, extraction_source)
    now = datetime.now(timezone.utc)
    entry = TimelineEntry(
        id=f"entry-{uuid4()}",
        patient_id=patient_id,
        clinic_id=record.patient.clinic_id,
        author_role=AuthorRole.SYSTEM,
        author_id="system-ai-scribe",
        author_name="AI Scribe",
        timestamp=now,
        entry_type=(
            "patient_session_summary"
            if context.role == UserRole.PATIENT
            else payload.interaction_type
        ),
        title=extraction.title,
        content=redaction.text,
        visibility_scope=(
            VisibilityScope.CARE_TEAM
            if context.role == UserRole.PATIENT
            else VisibilityScope.CLINICIAN
        ),
        version=1,
        source_label=f"{payload.interaction_type} · {payload.source_id}",
    )
    highlights: list[Highlight] = []
    for signal in extraction.signals:
        start = entry.content.index(signal.source_snippet)
        evaluation = evaluate_signal(
            text=signal.text,
            category=signal.category,
            proposed_risk=signal.risk_level,
            extraction_confidence=signal.extraction_confidence,
            provenance_confidence=ProvenanceConfidence.HIGH,
        )
        highlights.append(
            Highlight(
                id=f"highlight-{uuid4()}",
                patient_id=patient_id,
                text=signal.text,
                category=signal.category,
                risk_level=evaluation.risk_level,
                risk_reason=signal.risk_reason,
                trust_status=evaluation.trust_status,
                importance_score=evaluation.importance_score,
                extraction_confidence=signal.extraction_confidence,
                confidence_reason=signal.confidence_reason,
                importance_reason=evaluation.importance_reason,
                risk_floor_applied=evaluation.risk_floor_applied,
                risk_floor_reason=evaluation.risk_floor_reason,
                abstained_from_glance=evaluation.abstained_from_glance,
                abstention_reason=evaluation.abstention_reason,
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
    conflicts = detect_conflicts(record, entry, highlights, now)
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
        ingest_key, entry, highlights, conflicts, version, audit_log
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
        promoted_count=sum(not item.abstained_from_glance for item in highlights),
        review_queue_count=sum(item.abstained_from_glance for item in highlights),
        conflicts=conflicts,
    )


@router.post(
    "/{patient_id}/highlights/{highlight_id}/interactions",
    response_model=InteractionEvent,
    status_code=status.HTTP_201_CREATED,
)
def create_highlight_interaction(
    patient_id: str,
    highlight_id: str,
    payload: CreateInteractionRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> InteractionEvent:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    if payload.event_type in {"pin", "less_relevant"}:
        require_action(context, Action.PIN_HIGHLIGHT)
    highlight = next((item for item in record.highlights if item.id == highlight_id), None)
    if highlight is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    source_entry = next(
        (
            item
            for item in record.timeline_entries
            if item.id == highlight.provenance_pointer.entry_id
        ),
        None,
    )
    if source_entry is None:
        raise HTTPException(status_code=404, detail="Highlight source not found")
    require_action(context, entry_action(source_entry))
    event = InteractionEvent(
        id=f"interaction-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        event_type=payload.event_type,
        highlight_id=highlight.id,
        extracted_topic=highlight.category.value,
        weight_delta={"pin": 4, "highlight": 1, "less_relevant": -2}[payload.event_type],
        created_at=datetime.now(timezone.utc),
    )
    return repository.add_interaction_event(event)


@router.post(
    "/{patient_id}/highlights/{highlight_id}/decision",
    response_model=Highlight,
)
def decide_highlight(
    patient_id: str,
    highlight_id: str,
    payload: HighlightDecisionRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> Highlight:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    action = (
        Action.ACCEPT_HIGHLIGHT
        if payload.decision == "accept"
        else Action.REJECT_HIGHLIGHT
    )
    require_action(context, action)
    highlight = next((item for item in record.highlights if item.id == highlight_id), None)
    if highlight is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    source_entry = next(
        (
            item
            for item in record.timeline_entries
            if item.id == highlight.provenance_pointer.entry_id
        ),
        None,
    )
    if source_entry is None:
        raise HTTPException(status_code=409, detail="Highlight source is unavailable")
    require_action(context, entry_action(source_entry))

    now = datetime.now(timezone.utc)
    accepted = payload.decision == "accept"
    trust_status = (
        TrustStatus.CLINICIAN_CONFIRMED if accepted else TrustStatus.REJECTED
    )
    reason = (payload.reason or "").strip() or (
        "Accepted after clinical source review."
        if accepted
        else "Rejected after clinical source review."
    )
    audit_log = AuditLog(
        id=f"audit-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        action="accept_highlight" if accepted else "reject_highlight",
        entity_type="highlight",
        entity_id=highlight_id,
        changed_fields=[
            "trust_status",
            "reviewed_by",
            "reviewed_by_role",
            "reviewed_at",
            "review_reason",
        ],
        created_at=now,
        request_id=f"request-{uuid4()}",
    )
    updated = repository.decide_highlight(
        patient_id,
        highlight_id,
        trust_status,
        context.actor_id,
        context.role,
        now,
        reason,
        audit_log,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    return updated


@router.post(
    "/{patient_id}/entries/{entry_id}/highlights",
    response_model=Highlight,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_highlight(
    patient_id: str,
    entry_id: str,
    payload: CreateManualHighlightRequest,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> Highlight:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Patient record not found")
    require_clinic_scope(context, record.patient.clinic_id)
    require_action(context, Action.CREATE_HIGHLIGHT)
    entry = next((item for item in record.timeline_entries if item.id == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    require_action(context, entry_action(entry))
    if entry.author_role != AuthorRole.SYSTEM or not (
        entry.entry_type.startswith("ai_")
        or entry.entry_type == "patient_session_summary"
    ):
        raise HTTPException(
            status_code=400,
            detail="Manual highlights can be created only from AI-scribed entries",
        )
    if payload.start_offset >= payload.end_offset or payload.end_offset > len(entry.content):
        raise HTTPException(status_code=400, detail="Selected source offsets are invalid")
    resolved_quote = entry.content[payload.start_offset : payload.end_offset]
    if resolved_quote != payload.source_quote:
        raise HTTPException(
            status_code=409,
            detail="Selected text no longer matches the stored source",
        )

    evaluation = evaluate_signal(
        text=payload.source_quote,
        category=SignalCategory(payload.category),
        proposed_risk=RiskLevel(payload.risk_level),
        extraction_confidence="high",
        provenance_confidence=ProvenanceConfidence.HIGH,
    )
    now = datetime.now(timezone.utc)
    highlight = Highlight(
        id=f"highlight-{uuid4()}",
        patient_id=patient_id,
        text=payload.source_quote,
        category=payload.category,
        risk_level=evaluation.risk_level,
        risk_reason=payload.risk_reason,
        trust_status=TrustStatus.CLINICIAN_CONFIRMED,
        importance_score=evaluation.importance_score,
        extraction_confidence="high",
        confidence_reason="Exact phrase manually selected and confirmed by a clinical reviewer.",
        importance_reason=evaluation.importance_reason,
        risk_floor_applied=evaluation.risk_floor_applied,
        risk_floor_reason=evaluation.risk_floor_reason,
        abstained_from_glance=False,
        abstention_reason=None,
        reviewed_by=context.actor_id,
        reviewed_by_role=context.role,
        reviewed_at=now,
        review_reason="Created from an exact manual source selection.",
        provenance_pointer=ProvenancePointer(
            id=f"provenance-{uuid4()}",
            patient_id=patient_id,
            entry_id=entry.id,
            source_type="manual_selection",
            source_id=entry.id,
            source_quote=payload.source_quote,
            start_offset=payload.start_offset,
            end_offset=payload.end_offset,
            offset_confidence=ProvenanceConfidence.HIGH,
        ),
        created_at=now,
    )
    audit_log = AuditLog(
        id=f"audit-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        action="create_manual_highlight",
        entity_type="highlight",
        entity_id=highlight.id,
        changed_fields=[
            "highlight",
            "category",
            "risk_level",
            "trust_status",
            "provenance_pointer",
        ],
        created_at=now,
        request_id=f"request-{uuid4()}",
    )
    if not repository.add_manual_highlight(highlight, audit_log):
        raise HTTPException(
            status_code=409,
            detail="This exact source span is already highlighted",
        )
    return highlight


def require_entry_edit(context: AuthContext, entry: TimelineEntry) -> None:
    if context.role == UserRole.ADMIN:
        return
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
        if entry.author_id != context.actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Clinicians can edit only their own clinician notes",
            )
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
    created = repository.add_comment(comment)
    record_entry_interactions(repository, record, entry_id, context, "comment")
    return created


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
    record_entry_interactions(repository, record, entry_id, context, "edit")
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
