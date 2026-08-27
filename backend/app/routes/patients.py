from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import (
    Action,
    get_auth_context,
    require_action,
    require_clinic_scope,
)
from app.dependencies import get_repository
from app.models import (
    AuditLog,
    AuthContext,
    AuthorRole,
    CreateEntryRequest,
    PatientRecord,
    TimelineEntry,
    UpdateEntryRequest,
    UserRole,
    Version,
    VisibilityScope,
)
from app.repositories import PatientRecordRepository, VersionConflictError
from app.services.patient_records import filter_patient_record

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("/{patient_id}/record", response_model=PatientRecord)
def get_patient_record(
    patient_id: str,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> PatientRecord:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient record not found",
        )
    require_action(context, Action.READ_PATIENT_SUMMARY)
    return filter_patient_record(record, context)


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
    return repository.add_timeline_entry(entry)


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

    if entry.entry_type == "staff_note":
        require_action(context, Action.EDIT_STAFF_NOTE)
        if context.role == UserRole.STAFF and entry.author_id != context.actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff can edit only their own staff notes",
            )
    elif entry.entry_type in {"clinician_note", "clinician_section"}:
        require_action(context, Action.EDIT_CLINICIAN_SECTION)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This entry type is immutable through the note editor",
        )

    now = datetime.now(timezone.utc)
    next_version = entry.version + 1
    version = Version(
        id=f"version-{uuid4()}",
        patient_id=patient_id,
        entry_id=entry_id,
        version_number=next_version,
        content_snapshot=payload.content,
        changed_by=context.actor_id,
        changed_by_role=AuthorRole(context.role.value),
        created_at=now,
        change_summary="Timeline entry edited",
    )
    audit_log = AuditLog(
        id=f"audit-{uuid4()}",
        patient_id=patient_id,
        actor_id=context.actor_id,
        actor_role=AuthorRole(context.role.value),
        action="update_entry",
        entity_type="timeline_entry",
        entity_id=entry_id,
        changed_fields=["content", "version"],
        created_at=now,
        request_id=f"request-{uuid4()}",
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
