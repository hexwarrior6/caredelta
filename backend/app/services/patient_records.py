from app.auth import Action, can, require_clinic_scope
from app.models import AuthContext, AuthorRole, PatientRecord, TimelineEntry, VisibilityScope


def _entry_action(entry: TimelineEntry) -> Action:
    if entry.visibility_scope == VisibilityScope.PATIENT:
        return Action.READ_PATIENT_INSTRUCTIONS
    if (
        entry.author_role == AuthorRole.PATIENT
        or entry.entry_type == "patient_session_summary"
    ):
        return Action.READ_PATIENT_SUMMARY
    if entry.author_role == AuthorRole.STAFF or entry.entry_type == "staff_note":
        return Action.READ_STAFF_NOTES
    if entry.author_role == AuthorRole.SYSTEM or entry.entry_type.startswith("ai_"):
        return Action.READ_RAW_AI_TRANSCRIPT
    return Action.READ_CLINICIAN_SECTIONS


def filter_patient_record(record: PatientRecord, context: AuthContext) -> PatientRecord:
    require_clinic_scope(context, record.patient.clinic_id)

    visible_entries = [
        entry for entry in record.timeline_entries if can(context.role, _entry_action(entry))
    ]
    visible_entry_ids = {entry.id for entry in visible_entries}

    # A signal is hidden when its source entry is hidden. This prevents provenance
    # metadata from becoming a side channel for restricted note content.
    highlights = [
        highlight
        for highlight in record.highlights
        if highlight.provenance_pointer.entry_id in visible_entry_ids
        and (
            context.role.value != "patient"
            or highlight.trust_status.value == "clinician_confirmed"
        )
    ]
    tasks = [task for task in record.tasks if task.source_entry_id in visible_entry_ids]
    comments = (
        [comment for comment in record.comments if comment.entry_id in visible_entry_ids]
        if can(context.role, Action.READ_INTERNAL_COMMENTS)
        else []
    )
    versions = [
        version
        for version in record.versions
        if version.entry_id in visible_entry_ids
        and can(context.role, Action.READ_AUDIT_LOG)
    ]
    audit_logs = record.audit_logs if can(context.role, Action.READ_AUDIT_LOG) else []
    interaction_events = (
        record.interaction_events
        if can(context.role, Action.READ_AUDIT_LOG)
        else []
    )
    conflicts = [
        conflict
        for conflict in record.conflicts
        if set(conflict.source_entry_ids).issubset(visible_entry_ids)
    ]

    return record.model_copy(
        update={
            "highlights": highlights,
            "tasks": tasks,
            "timeline_entries": visible_entries,
            "comments": comments,
            "versions": versions,
            "audit_logs": audit_logs,
            "interaction_events": interaction_events,
            "conflicts": conflicts,
        }
    )
