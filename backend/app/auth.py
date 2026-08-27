import base64, hashlib, hmac, json, time
from enum import StrEnum
from typing import Annotated
from fastapi import Header, HTTPException, status
from app.config import get_settings
from app.models import AuthContext, DemoIdentity, UserRole

class Action(StrEnum):
    READ_PATIENT_SUMMARY="read_patient_summary"; READ_PATIENT_INSTRUCTIONS="read_patient_instructions"; READ_STAFF_NOTES="read_staff_notes"; READ_CLINICIAN_SECTIONS="read_clinician_sections"; READ_RAW_AI_TRANSCRIPT="read_raw_ai_transcript"; READ_INTERNAL_COMMENTS="read_internal_comments"; READ_REVISION_HISTORY="read_revision_history"; CREATE_STAFF_NOTE="create_staff_note"; EDIT_STAFF_NOTE="edit_staff_note"; EDIT_CLINICIAN_SECTION="edit_clinician_section"; CREATE_INTERNAL_COMMENT="create_internal_comment"; RESOLVE_INTERNAL_COMMENT="resolve_internal_comment"; ACCEPT_HIGHLIGHT="accept_highlight"; REJECT_HIGHLIGHT="reject_highlight"; PIN_HIGHLIGHT="pin_highlight"; ROLLBACK_ENTRY="rollback_entry"; READ_AUDIT_LOG="read_audit_log"; INGEST_AI_NOTE="ingest_ai_note"; PATIENT_AI_CHAT="patient_ai_chat"

care_team=frozenset({UserRole.STAFF,UserRole.CLINICIAN,UserRole.ADMIN})
ACTION_MATRIX={
 Action.READ_PATIENT_SUMMARY:frozenset(UserRole), Action.READ_PATIENT_INSTRUCTIONS:frozenset(UserRole),
 Action.READ_STAFF_NOTES:care_team, Action.READ_CLINICIAN_SECTIONS:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}), Action.READ_RAW_AI_TRANSCRIPT:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}),
 Action.READ_INTERNAL_COMMENTS:care_team, Action.READ_REVISION_HISTORY:care_team, Action.CREATE_STAFF_NOTE:frozenset({UserRole.STAFF,UserRole.ADMIN}), Action.EDIT_STAFF_NOTE:frozenset({UserRole.STAFF,UserRole.ADMIN}),
 Action.EDIT_CLINICIAN_SECTION:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}), Action.CREATE_INTERNAL_COMMENT:care_team, Action.RESOLVE_INTERNAL_COMMENT:care_team,
 Action.ACCEPT_HIGHLIGHT:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}), Action.REJECT_HIGHLIGHT:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}), Action.PIN_HIGHLIGHT:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}),
 Action.ROLLBACK_ENTRY:care_team, Action.READ_AUDIT_LOG:frozenset({UserRole.CLINICIAN,UserRole.ADMIN}), Action.INGEST_AI_NOTE:frozenset({UserRole.PATIENT,UserRole.CLINICIAN,UserRole.ADMIN}),
 Action.PATIENT_AI_CHAT:frozenset({UserRole.PATIENT}),
}
PATIENT_IDS=["patient-syn-001","patient-syn-002","patient-syn-003"]
def _identity(id,name,role,key,default,available): return DemoIdentity(id=id,display_name=name,role=role,clinic_id="clinic-syn-orchard",demo_key=key,default_patient_id=default,available_patient_ids=available)
DEMO_IDENTITIES={
 "patient-syn-001":_identity("patient-syn-001","Elaine Tan","patient","ELAINE-DEMO-2026","patient-syn-001",["patient-syn-001"]),
 "patient-syn-002":_identity("patient-syn-002","Amir Rahman","patient","AMIR-DEMO-2026","patient-syn-002",["patient-syn-002"]),
 "patient-syn-003":_identity("patient-syn-003","Sofia Chen","patient","SOFIA-DEMO-2026","patient-syn-003",["patient-syn-003"]),
 "staff-syn-chen":_identity("staff-syn-chen","Alicia Chen","staff","STAFF-DEMO-2026",PATIENT_IDS[0],PATIENT_IDS),
 "clinician-syn-lim":_identity("clinician-syn-lim","Dr. Maya Lim","clinician","CLINICIAN-DEMO-2026",PATIENT_IDS[0],PATIENT_IDS),
 "admin-syn-morgan":_identity("admin-syn-morgan","Jordan Morgan","admin","ADMIN-DEMO-2026",PATIENT_IDS[0],PATIENT_IDS),
}
def _enc(value:bytes)->str: return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
def _dec(value:str)->bytes: return base64.urlsafe_b64decode(value+"="*(-len(value)%4))
def issue_demo_token(identity:DemoIdentity,ttl:int=28800)->str:
 payload=_enc(json.dumps({"sub":identity.id,"role":identity.role.value,"clinic":identity.clinic_id,"exp":int(time.time())+ttl},separators=(",",":")).encode())
 signature=hmac.new(get_settings().demo_auth_secret.encode(),payload.encode(),hashlib.sha256).digest()
 return f"{payload}.{_enc(signature)}"
def verify_demo_token(token:str)->AuthContext:
 try:
  payload_text,supplied=token.split(".",1); expected=hmac.new(get_settings().demo_auth_secret.encode(),payload_text.encode(),hashlib.sha256).digest()
  if not hmac.compare_digest(expected,_dec(supplied)): raise ValueError
  payload=json.loads(_dec(payload_text)); identity=DEMO_IDENTITIES[payload["sub"]]
  if int(payload["exp"])<int(time.time()) or payload["role"]!=identity.role.value or payload["clinic"]!=identity.clinic_id: raise ValueError
  return AuthContext(actor_id=identity.id,role=identity.role,clinic_id=identity.clinic_id)
 except (ValueError,KeyError,TypeError,json.JSONDecodeError): raise HTTPException(status_code=401,detail="Invalid or expired demo session") from None
def get_auth_context(patient_id:str,authorization:Annotated[str|None,Header()]=None,actor_id:Annotated[str|None,Header(alias="X-Actor-Id")]=None,actor_role:Annotated[UserRole|None,Header(alias="X-Actor-Role")]=None,clinic_id:Annotated[str|None,Header(alias="X-Clinic-Id")]=None)->AuthContext:
 context=None
 if authorization and authorization.startswith("Bearer "): context=verify_demo_token(authorization.removeprefix("Bearer ").strip())
 elif get_settings().allow_legacy_auth_headers and actor_id and actor_role and clinic_id: context=AuthContext(actor_id=actor_id,role=actor_role,clinic_id=clinic_id)
 if context:
  if context.role==UserRole.PATIENT and context.actor_id!=patient_id: raise HTTPException(status_code=403,detail="Patients can access only their own record")
  return context
 raise HTTPException(status_code=401,detail="Demo login required")
def can(role:UserRole,action:Action)->bool: return role in ACTION_MATRIX[action]
def require_action(context:AuthContext,action:Action)->None:
 if not can(context.role,action): raise HTTPException(status_code=403,detail=f"Role '{context.role}' cannot perform '{action}'")
def require_record_scope(context:AuthContext,patient_id:str,patient_clinic_id:str)->None:
 if context.clinic_id!=patient_clinic_id: raise HTTPException(status_code=403,detail="Patient is outside the actor's clinic scope")
 if context.role==UserRole.PATIENT and context.actor_id!=patient_id: raise HTTPException(status_code=403,detail="Patients can access only their own record")
def require_clinic_scope(context:AuthContext,patient_clinic_id:str)->None:
 if context.clinic_id!=patient_clinic_id: raise HTTPException(status_code=403,detail="Patient is outside the actor's clinic scope")
