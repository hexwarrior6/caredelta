from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AuthorRole(StrEnum):
    PATIENT = "patient"
    STAFF = "staff"
    CLINICIAN = "clinician"
    ADMIN = "admin"
    SYSTEM = "system"


class UserRole(StrEnum):
    PATIENT = "patient"
    STAFF = "staff"
    CLINICIAN = "clinician"
    ADMIN = "admin"


class VisibilityScope(StrEnum):
    PATIENT = "patient"
    CARE_TEAM = "care_team"
    CLINICIAN = "clinician"


class SignalCategory(StrEnum):
    NEW = "new"
    WORSENING = "worsening"
    RECURRING = "recurring"
    UNRESOLVED = "unresolved"
    CONTRADICTED = "contradicted"
    CONFIRMED = "confirmed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrustStatus(StrEnum):
    AI_SUGGESTED = "ai_suggested"
    CLINICIAN_CONFIRMED = "clinician_confirmed"
    NEEDS_REVIEW = "needs_review"


class Patient(BaseModel):
    id: str
    clinic_id: str
    display_name: str
    age: int = Field(ge=0, le=130)
    pronouns: str
    synthetic: bool = True
    summary: str
    active_conditions: list[str]
    allergies: list[str]
    last_visit_at: datetime


class TimelineEntry(BaseModel):
    id: str
    patient_id: str
    clinic_id: str
    author_role: AuthorRole
    author_id: str
    author_name: str
    timestamp: datetime
    entry_type: str
    title: str
    content: str
    visibility_scope: VisibilityScope
    version: int = Field(ge=1)
    source_label: str


class ProvenancePointer(BaseModel):
    id: str
    patient_id: str
    entry_id: str
    source_type: str
    source_id: str
    source_quote: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    offset_confidence: str


class Highlight(BaseModel):
    id: str
    patient_id: str
    text: str
    category: SignalCategory
    risk_level: RiskLevel
    risk_reason: str
    trust_status: TrustStatus
    importance_score: int = Field(ge=0, le=100)
    provenance_pointer: ProvenancePointer
    created_at: datetime


class Comment(BaseModel):
    id: str
    patient_id: str
    entry_id: str
    author_role: AuthorRole
    author_id: str
    author_name: str
    body: str
    created_at: datetime
    resolved: bool
    mentions: list[str] = Field(default_factory=list)


class Task(BaseModel):
    id: str
    patient_id: str
    title: str
    status: str
    priority: RiskLevel
    assigned_role: AuthorRole
    due_at: datetime
    source_entry_id: str


class Version(BaseModel):
    id: str
    patient_id: str
    entry_id: str
    version_number: int = Field(ge=1)
    content_snapshot: str
    changed_by: str
    changed_by_role: AuthorRole
    created_at: datetime
    change_summary: str


class AuditLog(BaseModel):
    id: str
    patient_id: str
    actor_id: str
    actor_role: AuthorRole
    action: str
    entity_type: str
    entity_id: str
    changed_fields: list[str]
    created_at: datetime
    request_id: str


class InteractionEvent(BaseModel):
    id: str
    patient_id: str
    actor_id: str
    actor_role: AuthorRole
    event_type: str
    highlight_id: str
    extracted_topic: str
    weight_delta: float
    created_at: datetime


class Conflict(BaseModel):
    id: str
    patient_id: str
    conflict_type: str
    summary: str
    severity: RiskLevel
    status: str
    source_entry_ids: list[str]
    resolution: str | None = None
    detected_at: datetime


class PatientRecord(BaseModel):
    patient: Patient
    highlights: list[Highlight]
    tasks: list[Task]
    timeline_entries: list[TimelineEntry]
    comments: list[Comment]
    versions: list[Version]
    audit_logs: list[AuditLog]
    interaction_events: list[InteractionEvent]
    conflicts: list[Conflict]
    generated_at: datetime


class AuthContext(BaseModel):
    actor_id: str
    role: UserRole
    clinic_id: str


class CreateEntryRequest(BaseModel):
    section: Literal["staff_note", "clinician_section"]
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=10_000)


class UpdateEntryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    expected_version: int = Field(ge=1)
