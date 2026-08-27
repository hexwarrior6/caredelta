from copy import deepcopy
from typing import Protocol

from app.models import PatientRecord


class PatientRecordRepository(Protocol):
    def get_patient_record(self, patient_id: str) -> PatientRecord | None: ...


class MemoryRepository:
    """In-process repository used by the Phase 2 demo and test suite."""

    def __init__(self, records: list[PatientRecord]) -> None:
        self._records = {record.patient.id: deepcopy(record) for record in records}

    def get_patient_record(self, patient_id: str) -> PatientRecord | None:
        record = self._records.get(patient_id)
        return deepcopy(record) if record else None
