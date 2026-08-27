export type RiskLevel = "low" | "medium" | "high";
export type UserRole = "patient" | "staff" | "clinician" | "admin";
export type AIInteractionType =
  | "ai_doctor_consult_summary"
  | "ai_nurse_consult_summary"
  | "ai_patient_session_summary";
export type ProvenanceConfidence = "high" | "medium" | "low";
export type ExtractionConfidence = "high" | "medium" | "low";
export type SignalCategory =
  | "new"
  | "worsening"
  | "recurring"
  | "unresolved"
  | "contradicted"
  | "confirmed";

export type Patient = {
  id: string;
  clinic_id: string;
  display_name: string;
  age: number;
  pronouns: string;
  synthetic: boolean;
  summary: string;
  active_conditions: string[];
  allergies: string[];
  last_visit_at: string;
};

export type ProvenancePointer = {
  id: string;
  entry_id: string;
  source_type: string;
  source_id: string;
  source_quote: string;
  start_offset: number;
  end_offset: number;
  offset_confidence: ProvenanceConfidence;
};

export type Highlight = {
  id: string;
  text: string;
  category: SignalCategory;
  risk_level: RiskLevel;
  risk_reason: string;
  trust_status: "ai_suggested" | "clinician_confirmed" | "needs_review";
  importance_score: number;
  extraction_confidence: ExtractionConfidence;
  confidence_reason: string;
  importance_reason: string;
  risk_floor_applied: boolean;
  risk_floor_reason: string | null;
  abstained_from_glance: boolean;
  abstention_reason: string | null;
  provenance_pointer: ProvenancePointer;
  created_at: string;
};

export type TimelineEntry = {
  id: string;
  author_role: UserRole | "system";
  author_id: string;
  author_name: string;
  timestamp: string;
  entry_type: string;
  title: string;
  content: string;
  version: number;
  source_label: string;
};

export type Version = {
  id: string;
  entry_id: string;
  version_number: number;
  content_snapshot: string;
  changed_by: string;
  changed_by_role: UserRole | "system";
  created_at: string;
  change_summary: string;
};

export type PatientTask = {
  id: string;
  title: string;
  status: string;
  priority: RiskLevel;
  assigned_role: string;
  due_at: string;
  source_entry_id: string;
};

export type Comment = {
  id: string;
  entry_id: string;
  author_role: UserRole;
  author_name: string;
  body: string;
  created_at: string;
  resolved: boolean;
  mentions: string[];
  assigned_role: UserRole | null;
};

export type Conflict = {
  id: string;
  summary: string;
  severity: RiskLevel;
  status: string;
  source_entry_ids: string[];
};

export type PatientRecord = {
  patient: Patient;
  highlights: Highlight[];
  tasks: PatientTask[];
  timeline_entries: TimelineEntry[];
  comments: Comment[];
  versions: Version[];
  audit_logs: unknown[];
  interaction_events: unknown[];
  conflicts: Conflict[];
  review_queue: Highlight[];
  generated_at: string;
  highlight_pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
  };
};

export type AIRedactionPreview = {
  redacted_text: string;
  redacted_phi_types: string[];
  warning: string | null;
};

export type AIIngestResult = {
  entry: TimelineEntry;
  highlights: Highlight[];
  extraction_method: "deepseek" | "fallback";
  fallback_reason:
    | "llm_unavailable"
    | "invalid_json"
    | "timeout"
    | "provenance_unresolved"
    | null;
  summary: string;
  redacted_phi_types: string[];
  promoted_count: number;
  review_queue_count: number;
};
