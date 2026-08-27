export type RiskLevel = "low" | "medium" | "high";
export type UserRole = "patient" | "staff" | "clinician" | "admin";
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
  offset_confidence: string;
};

export type Highlight = {
  id: string;
  text: string;
  category: SignalCategory;
  risk_level: RiskLevel;
  risk_reason: string;
  trust_status: "ai_suggested" | "clinician_confirmed" | "needs_review";
  importance_score: number;
  provenance_pointer: ProvenancePointer;
  created_at: string;
};

export type TimelineEntry = {
  id: string;
  author_role: UserRole | "system";
  author_name: string;
  timestamp: string;
  entry_type: string;
  title: string;
  content: string;
  version: number;
  source_label: string;
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
  versions: unknown[];
  audit_logs: unknown[];
  interaction_events: unknown[];
  conflicts: Conflict[];
  generated_at: string;
};
