from copy import deepcopy
from typing import Protocol

from app.models import AuditLog, Comment, PatientRecord, TimelineEntry, Version


class VersionConflictError(Exception):
    pass


class PatientRecordRepository(Protocol):
    def get_patient_record(self, patient_id: str) -> PatientRecord | None: ...

    def add_timeline_entry(self, entry: TimelineEntry) -> TimelineEntry: ...

    def add_comment(self, comment: Comment) -> Comment: ...

    def update_comment_status(
        self, patient_id: str, comment_id: str, resolved: bool
    ) -> Comment | None: ...

    def update_timeline_entry(
        self,
        patient_id: str,
        entry_id: str,
        content: str,
        expected_version: int,
        version: Version,
        audit_log: AuditLog,
    ) -> TimelineEntry | None: ...


class MemoryRepository:
    """In-process repository used by the local demo and test suite."""

    def __init__(self, records: list[PatientRecord]) -> None:
        self._records = {record.patient.id: deepcopy(record) for record in records}

    def get_patient_record(self, patient_id: str) -> PatientRecord | None:
        record = self._records.get(patient_id)
        return deepcopy(record) if record else None

    def add_timeline_entry(self, entry: TimelineEntry) -> TimelineEntry:
        record = self._records[entry.patient_id]
        record.timeline_entries.insert(0, deepcopy(entry))
        return deepcopy(entry)

    def add_comment(self, comment: Comment) -> Comment:
        record = self._records[comment.patient_id]
        record.comments.append(deepcopy(comment))
        return deepcopy(comment)

    def update_comment_status(
        self, patient_id: str, comment_id: str, resolved: bool
    ) -> Comment | None:
        record = self._records.get(patient_id)
        if record is None:
            return None
        for index, comment in enumerate(record.comments):
            if comment.id != comment_id:
                continue
            updated = comment.model_copy(update={"resolved": resolved})
            record.comments[index] = updated
            return deepcopy(updated)
        return None

    def update_timeline_entry(
        self,
        patient_id: str,
        entry_id: str,
        content: str,
        expected_version: int,
        version: Version,
        audit_log: AuditLog,
    ) -> TimelineEntry | None:
        record = self._records.get(patient_id)
        if record is None:
            return None
        for index, entry in enumerate(record.timeline_entries):
            if entry.id != entry_id:
                continue
            if entry.version != expected_version:
                raise VersionConflictError
            updated = entry.model_copy(
                update={"content": content, "version": entry.version + 1}
            )
            record.timeline_entries[index] = updated
            record.versions.append(deepcopy(version))
            record.audit_logs.append(deepcopy(audit_log))
            return deepcopy(updated)
        return None
