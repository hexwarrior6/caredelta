from enum import StrEnum
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.models import AuthContext, UserRole


class Action(StrEnum):
    READ_PATIENT_SUMMARY = "read_patient_summary"
    READ_PATIENT_INSTRUCTIONS = "read_patient_instructions"
    READ_STAFF_NOTES = "read_staff_notes"
    READ_CLINICIAN_SECTIONS = "read_clinician_sections"
    READ_RAW_AI_TRANSCRIPT = "read_raw_ai_transcript"
    READ_INTERNAL_COMMENTS = "read_internal_comments"
    CREATE_STAFF_NOTE = "create_staff_note"
    EDIT_STAFF_NOTE = "edit_staff_note"
    EDIT_CLINICIAN_SECTION = "edit_clinician_section"
    CREATE_INTERNAL_COMMENT = "create_internal_comment"
    RESOLVE_INTERNAL_COMMENT = "resolve_internal_comment"
    ACCEPT_HIGHLIGHT = "accept_highlight"
    REJECT_HIGHLIGHT = "reject_highlight"
    PIN_HIGHLIGHT = "pin_highlight"
    ROLLBACK_ENTRY = "rollback_entry"
    READ_AUDIT_LOG = "read_audit_log"


ACTION_MATRIX: dict[Action, frozenset[UserRole]] = {
    Action.READ_PATIENT_SUMMARY: frozenset(UserRole),
    Action.READ_PATIENT_INSTRUCTIONS: frozenset(UserRole),
    Action.READ_STAFF_NOTES: frozenset(
        {UserRole.STAFF, UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.READ_CLINICIAN_SECTIONS: frozenset(
        {UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.READ_RAW_AI_TRANSCRIPT: frozenset(
        {UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.READ_INTERNAL_COMMENTS: frozenset(
        {UserRole.STAFF, UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.CREATE_STAFF_NOTE: frozenset({UserRole.STAFF, UserRole.ADMIN}),
    Action.EDIT_STAFF_NOTE: frozenset({UserRole.STAFF, UserRole.ADMIN}),
    Action.EDIT_CLINICIAN_SECTION: frozenset(
        {UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.CREATE_INTERNAL_COMMENT: frozenset(
        {UserRole.STAFF, UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.RESOLVE_INTERNAL_COMMENT: frozenset(
        {UserRole.STAFF, UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.ACCEPT_HIGHLIGHT: frozenset({UserRole.CLINICIAN, UserRole.ADMIN}),
    Action.REJECT_HIGHLIGHT: frozenset({UserRole.CLINICIAN, UserRole.ADMIN}),
    Action.PIN_HIGHLIGHT: frozenset({UserRole.CLINICIAN, UserRole.ADMIN}),
    Action.ROLLBACK_ENTRY: frozenset(
        {UserRole.STAFF, UserRole.CLINICIAN, UserRole.ADMIN}
    ),
    Action.READ_AUDIT_LOG: frozenset({UserRole.CLINICIAN, UserRole.ADMIN}),
}


def get_auth_context(
    actor_id: Annotated[str, Header(alias="X-Actor-Id")],
    actor_role: Annotated[UserRole, Header(alias="X-Actor-Role")],
    clinic_id: Annotated[str, Header(alias="X-Clinic-Id")],
) -> AuthContext:
    """Build demo auth context from headers that stand in for verified claims.

    Production must replace this transport with signed session/JWT claims. All
    authorization decisions remain server-side and do not trust UI visibility.
    """
    return AuthContext(actor_id=actor_id, role=actor_role, clinic_id=clinic_id)


def can(role: UserRole, action: Action) -> bool:
    return role in ACTION_MATRIX[action]


def require_action(context: AuthContext, action: Action) -> None:
    if not can(context.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{context.role}' cannot perform '{action}'",
        )


def require_clinic_scope(context: AuthContext, patient_clinic_id: str) -> None:
    if context.clinic_id != patient_clinic_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient is outside the actor's clinic scope",
        )
