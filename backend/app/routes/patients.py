from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_repository
from app.models import PatientRecord
from app.repositories import PatientRecordRepository

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("/{patient_id}/record", response_model=PatientRecord)
def get_patient_record(
    patient_id: str,
    repository: Annotated[PatientRecordRepository, Depends(get_repository)],
) -> PatientRecord:
    record = repository.get_patient_record(patient_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient record not found",
        )
    return record
