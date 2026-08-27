from copy import deepcopy
from typing import Any, Protocol

from pymongo.collection import Collection

from app.models import (
    AuditLog,
    Comment,
    Conflict,
    Highlight,
    InteractionEvent,
    PatientRecord,
    TimelineEntry,
    Version,
)


class VersionConflictError(Exception):
    pass


class PatientRecordRepository(Protocol):
    def get_patient_record(self, patient_id: str) -> PatientRecord | None: ...

    def add_timeline_entry(
        self, entry: TimelineEntry, version: Version, audit_log: AuditLog
    ) -> TimelineEntry: ...

    def add_comment(self, comment: Comment) -> Comment: ...

    def add_interaction_event(self, event: InteractionEvent) -> InteractionEvent: ...

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

    def add_ai_ingest(
        self,
        ingest_key: str,
        entry: TimelineEntry,
        highlights: list[Highlight],
        conflicts: list[Conflict],
        version: Version,
        audit_log: AuditLog,
    ) -> bool: ...


class MemoryRepository:
    """In-process repository used by the local demo and test suite."""

    def __init__(self, records: list[PatientRecord]) -> None:
        self._records = {record.patient.id: deepcopy(record) for record in records}
        self._ingest_keys = {
            record.patient.id: {
                f"{highlight.provenance_pointer.source_type}:{highlight.provenance_pointer.source_id}"
                for highlight in record.highlights
                if highlight.provenance_pointer.source_type.startswith("ai_")
            }
            for record in records
        }

    def get_patient_record(self, patient_id: str) -> PatientRecord | None:
        record = self._records.get(patient_id)
        return deepcopy(record) if record else None

    def add_timeline_entry(
        self, entry: TimelineEntry, version: Version, audit_log: AuditLog
    ) -> TimelineEntry:
        record = self._records[entry.patient_id]
        record.timeline_entries.insert(0, deepcopy(entry))
        record.versions.append(deepcopy(version))
        record.audit_logs.append(deepcopy(audit_log))
        return deepcopy(entry)

    def add_comment(self, comment: Comment) -> Comment:
        record = self._records[comment.patient_id]
        record.comments.append(deepcopy(comment))
        return deepcopy(comment)

    def add_interaction_event(self, event: InteractionEvent) -> InteractionEvent:
        self._records[event.patient_id].interaction_events.append(deepcopy(event))
        return deepcopy(event)

    def add_ai_ingest(
        self,
        ingest_key: str,
        entry: TimelineEntry,
        highlights: list[Highlight],
        conflicts: list[Conflict],
        version: Version,
        audit_log: AuditLog,
    ) -> bool:
        if ingest_key in self._ingest_keys[entry.patient_id]:
            return False
        record = self._records[entry.patient_id]
        self._ingest_keys[entry.patient_id].add(ingest_key)
        record.timeline_entries.insert(0, deepcopy(entry))
        record.highlights = deepcopy(highlights) + record.highlights
        record.conflicts = deepcopy(conflicts) + record.conflicts
        record.versions.append(deepcopy(version))
        record.audit_logs.append(deepcopy(audit_log))
        return True

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


class MongoRepository:
    """MongoDB-backed patient aggregate repository used by application runtimes."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def initialize(self, seed_record: PatientRecord) -> None:
        self._collection.database.client.admin.command("ping")
        self._collection.create_index("patient.id", unique=True)
        self._collection.create_index("patient.clinic_id")
        self._collection.create_index("timeline_entries.id")
        self._collection.create_index("comments.id")
        self._collection.update_one(
            {"patient.id": seed_record.patient.id},
            {"$setOnInsert": seed_record.model_dump(mode="python")},
            upsert=True,
        )
        record = self.get_patient_record(seed_record.patient.id)
        if record is None:
            return
        ingest_keys = sorted(
            {
                f"{highlight.provenance_pointer.source_type}:{highlight.provenance_pointer.source_id}"
                for highlight in record.highlights
                if highlight.provenance_pointer.source_type.startswith("ai_")
            }
        )
        if ingest_keys:
            self._collection.update_one(
                {"patient.id": record.patient.id},
                {"$addToSet": {"ingest_source_keys": {"$each": ingest_keys}}},
            )
        known_versions = {
            (version.entry_id, version.version_number) for version in record.versions
        }
        missing_versions = [
            Version(
                id=f"version-backfill-{entry.id}-{entry.version}",
                patient_id=record.patient.id,
                entry_id=entry.id,
                version_number=entry.version,
                content_snapshot=entry.content,
                changed_by=entry.author_id,
                changed_by_role=entry.author_role,
                created_at=entry.timestamp,
                change_summary="Current snapshot backfilled during migration",
            ).model_dump(mode="python")
            for entry in record.timeline_entries
            if entry.entry_type
            in {"staff_note", "clinician_note", "clinician_section"}
            and (entry.id, entry.version) not in known_versions
        ]
        for missing_version in missing_versions:
            self._collection.update_one(
                {
                    "patient.id": record.patient.id,
                    "versions": {
                        "$not": {
                            "$elemMatch": {
                                "entry_id": missing_version["entry_id"],
                                "version_number": missing_version["version_number"],
                            }
                        }
                    },
                },
                {"$push": {"versions": missing_version}},
            )

    def get_patient_record(self, patient_id: str) -> PatientRecord | None:
        document = self._collection.find_one(
            {"patient.id": patient_id}, projection={"_id": False}
        )
        return PatientRecord.model_validate(document) if document else None

    def add_timeline_entry(
        self, entry: TimelineEntry, version: Version, audit_log: AuditLog
    ) -> TimelineEntry:
        result = self._collection.update_one(
            {"patient.id": entry.patient_id},
            {
                "$push": {
                    "timeline_entries": {
                        "$each": [entry.model_dump(mode="python")],
                        "$position": 0,
                    },
                    "versions": version.model_dump(mode="python"),
                    "audit_logs": audit_log.model_dump(mode="python"),
                }
            },
        )
        if result.matched_count == 0:
            raise KeyError(entry.patient_id)
        return entry.model_copy(deep=True)

    def add_comment(self, comment: Comment) -> Comment:
        result = self._collection.update_one(
            {"patient.id": comment.patient_id},
            {"$push": {"comments": comment.model_dump(mode="python")}},
        )
        if result.matched_count == 0:
            raise KeyError(comment.patient_id)
        return comment.model_copy(deep=True)

    def add_interaction_event(self, event: InteractionEvent) -> InteractionEvent:
        result = self._collection.update_one(
            {"patient.id": event.patient_id},
            {"$push": {"interaction_events": event.model_dump(mode="python")}},
        )
        if result.matched_count == 0:
            raise KeyError(event.patient_id)
        return event.model_copy(deep=True)

    def add_ai_ingest(
        self,
        ingest_key: str,
        entry: TimelineEntry,
        highlights: list[Highlight],
        conflicts: list[Conflict],
        version: Version,
        audit_log: AuditLog,
    ) -> bool:
        result = self._collection.update_one(
            {
                "patient.id": entry.patient_id,
                "ingest_source_keys": {"$ne": ingest_key},
            },
            {
                "$addToSet": {"ingest_source_keys": ingest_key},
                "$push": {
                    "timeline_entries": {
                        "$each": [entry.model_dump(mode="python")],
                        "$position": 0,
                    },
                    "highlights": {
                        "$each": [item.model_dump(mode="python") for item in highlights],
                        "$position": 0,
                    },
                    "conflicts": {
                        "$each": [item.model_dump(mode="python") for item in conflicts],
                        "$position": 0,
                    },
                    "versions": version.model_dump(mode="python"),
                    "audit_logs": audit_log.model_dump(mode="python"),
                }
            },
        )
        return result.matched_count == 1

    def update_comment_status(
        self, patient_id: str, comment_id: str, resolved: bool
    ) -> Comment | None:
        result = self._collection.update_one(
            {"patient.id": patient_id, "comments.id": comment_id},
            {"$set": {"comments.$.resolved": resolved}},
        )
        if result.matched_count == 0:
            return None
        record = self.get_patient_record(patient_id)
        return (
            next(
                (comment for comment in record.comments if comment.id == comment_id),
                None,
            )
            if record
            else None
        )

    def update_timeline_entry(
        self,
        patient_id: str,
        entry_id: str,
        content: str,
        expected_version: int,
        version: Version,
        audit_log: AuditLog,
    ) -> TimelineEntry | None:
        result = self._collection.update_one(
            {
                "patient.id": patient_id,
                "timeline_entries": {
                    "$elemMatch": {"id": entry_id, "version": expected_version}
                },
            },
            {
                "$set": {"timeline_entries.$.content": content},
                "$inc": {"timeline_entries.$.version": 1},
                "$push": {
                    "versions": version.model_dump(mode="python"),
                    "audit_logs": audit_log.model_dump(mode="python"),
                },
            },
        )
        if result.matched_count == 0:
            current = self.get_patient_record(patient_id)
            if current is None:
                return None
            if any(entry.id == entry_id for entry in current.timeline_entries):
                raise VersionConflictError
            return None
        record = self.get_patient_record(patient_id)
        return (
            next(
                (entry for entry in record.timeline_entries if entry.id == entry_id),
                None,
            )
            if record
            else None
        )
