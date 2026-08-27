from app.auth import Action, can, require_clinic_scope
from app.models import (
    AuthContext,
    AuthorRole,
    HighlightPagination,
    PatientRecord,
    TimelineEntry,
    VisibilityScope,
)
from app.services.delta_engine import is_glance_eligible


def paginate_glance_highlights(highlights, page: int, page_size: int):
    ranked = sorted(
        highlights,
        key=lambda highlight: (highlight.importance_score, highlight.created_at),
        reverse=True,
    )
    total_items = len(ranked)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    resolved_page = min(page, total_pages)
    start = (resolved_page - 1) * page_size
    return (
        ranked[start : start + page_size],
        HighlightPagination(
            page=resolved_page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )


def entry_action(entry: TimelineEntry) -> Action:
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


def filter_patient_record(
    record: PatientRecord,
    context: AuthContext,
    highlight_page: int = 1,
    highlight_page_size: int = 3,
) -> PatientRecord:
    require_clinic_scope(context, record.patient.clinic_id)

    visible_entries = sorted(
        (
            entry
            for entry in record.timeline_entries
            if can(context.role, entry_action(entry))
        ),
        key=lambda entry: entry.timestamp,
        reverse=True,
    )
    visible_entry_ids = {entry.id for entry in visible_entries}

    # A signal is hidden when its source entry is hidden. This prevents provenance
    # metadata from becoming a side channel for restricted note content.
    visible_highlights = [
        highlight
        for highlight in record.highlights
        if highlight.provenance_pointer.entry_id in visible_entry_ids
    ]
    review_queue = (
        [
            highlight
            for highlight in visible_highlights
            if highlight.abstained_from_glance
            or highlight.trust_status.value == "needs_review"
        ]
        if context.role.value != "patient"
        else []
    )
    highlights, highlight_pagination = paginate_glance_highlights(
        [
            highlight
            for highlight in visible_highlights
            if is_glance_eligible(
                trust_status=highlight.trust_status,
                abstained=highlight.abstained_from_glance,
            )
            and (
                context.role.value != "patient"
                or highlight.trust_status.value == "clinician_confirmed"
            )
        ],
        highlight_page,
        highlight_page_size,
    )
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
        and can(context.role, Action.READ_REVISION_HISTORY)
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
            "review_queue": sorted(
                review_queue,
                key=lambda highlight: (highlight.importance_score, highlight.created_at),
                reverse=True,
            ),
            "highlight_pagination": highlight_pagination,
        }
    )
