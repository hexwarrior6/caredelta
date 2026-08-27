import re
from datetime import datetime
from uuid import uuid4

from app.models import Conflict, Highlight, PatientRecord, SignalCategory, TimelineEntry


_ALLERGY = re.compile(r"(?i)allerg|penicillin|amoxicillin|anaphyl")
_MEDICATION = re.compile(
    r"(?i)medication|medicine|dose|dosage|\b\d+(?:\.\d+)?\s?mg\b|amlodipine|insulin|inhaler"
)
_TASK = re.compile(r"(?i)pending|not yet|overdue|follow[- ]?up|book|arrange|await")


def _matching_entry(
    record: PatientRecord,
    new_entry: TimelineEntry,
    pattern: re.Pattern[str],
) -> TimelineEntry | None:
    return next(
        (
            entry
            for entry in record.timeline_entries
            if entry.id != new_entry.id and pattern.search(entry.content)
        ),
        None,
    )


def detect_conflicts(
    record: PatientRecord,
    new_entry: TimelineEntry,
    highlights: list[Highlight],
    detected_at: datetime,
) -> list[Conflict]:
    detected: list[Conflict] = []
    existing_keys = {
        (conflict.conflict_type, frozenset(conflict.source_entry_ids))
        for conflict in record.conflicts
        if conflict.status == "open"
    }

    for highlight in highlights:
        text = f"{highlight.text} {highlight.risk_reason}"
        conflict_type: str | None = None
        prior_entry: TimelineEntry | None = None
        summary: str | None = None

        if highlight.category == SignalCategory.CONTRADICTED and _ALLERGY.search(text):
            conflict_type = "allergy"
            prior_entry = _matching_entry(record, new_entry, _ALLERGY)
            summary = "New allergy evidence conflicts with the preserved allergy history."
        elif highlight.category == SignalCategory.CONTRADICTED and _MEDICATION.search(text):
            conflict_type = "medication"
            prior_entry = _matching_entry(record, new_entry, _MEDICATION)
            summary = "Medication or dose evidence conflicts with a preserved source entry."
        elif highlight.category in {SignalCategory.UNRESOLVED, SignalCategory.CONTRADICTED} and _TASK.search(text):
            conflict_type = "task"
            open_task = next(
                (
                    task
                    for task in record.tasks
                    if task.status == "open" and task.source_entry_id != new_entry.id
                ),
                None,
            )
            if open_task:
                prior_entry = next(
                    (
                        entry
                        for entry in record.timeline_entries
                        if entry.id == open_task.source_entry_id
                    ),
                    None,
                )
            summary = "The new interaction conflicts with or repeats an open care task."

        if conflict_type is None or prior_entry is None or summary is None:
            continue
        source_ids = [prior_entry.id, new_entry.id]
        key = (conflict_type, frozenset(source_ids))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        detected.append(
            Conflict(
                id=f"conflict-{uuid4()}",
                patient_id=record.patient.id,
                conflict_type=conflict_type,
                summary=summary,
                severity=highlight.risk_level,
                status="open",
                source_entry_ids=source_ids,
                detected_at=detected_at,
            )
        )
    return detected
