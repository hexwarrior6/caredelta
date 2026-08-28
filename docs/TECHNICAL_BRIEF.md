# CareDelta Technical Brief

## 1. Problem, product decision, and first principles

CareDelta is a source-backed clinical change radar for safer handoffs. Electronic
records are good at storing dated documents but poor at showing what changed,
what remains unresolved, and why a care-team member should trust a summary. The
product therefore does not attempt to summarize everything. It ranks a small
set of actionable changes and makes every assertion navigable to its source.

Three principles shape the implementation:

1. **Extraction before generation.** A signal must quote source text. If an
   exact span cannot be resolved, provenance is downgraded; low-confidence or
   conflicting output abstains from the Glance View.
2. **AI proposes; clinicians decide.** DeepSeek output is candidate information.
   Deterministic logic owns risk floors, ranking, conflict status, and trust.
3. **Safety boundaries live on the server.** The browser improves usability but
   never decides clinic scope, role permissions, patient visibility, or whether
   raw AI content may be returned.

The 72-hour scope favors a working, inspectable safety loop over broad EHR
integration. It uses synthetic data, passwordless demo identities, synchronous
short-transcript ingestion, full revision snapshots, and scoped conflict rules
for allergies, medication changes, and dependent tasks.

## 2. Architecture and runtime flow

```text
Browser / Next.js 16 (Vercel)
  | signed demo bearer token
  v
FastAPI clinical API (Railway)
  |-- RBAC + clinic-scope checks
  |-- timeline, comments, tasks, revisions, audit
  |-- PHI redaction -> DeepSeek adapter -> JSON validation
  |                         \-> deterministic fallback
  |-- delta, provenance, conflict, learning, abstention
  v
Repository contract
  |-- MongoRepository -> MongoDB Atlas (runtime)
  \-- MemoryRepository (isolated automated tests)
```

The hot patient-record path reads precomputed timeline entries, top highlights,
review items, tasks, comments, versions, audit metadata, and conflicts. It never
calls an LLM during page load. On AI ingest, known names, emails, phone numbers,
and common identifiers are redacted locally. DeepSeek must return validated JSON
and exact `source_snippet` values. Malformed output, timeout, unavailable service,
or unresolved extraction activates a deterministic rule extractor. The delta
engine then applies clinical risk floors, computes importance, detects scoped
conflicts, and routes unsafe candidates to review instead of the top card.

Deployment is split intentionally: Vercel retains native Next.js preview and
production builds; Railway runs a non-root FastAPI Docker image with `/health`
rollout checks; Atlas provides persistent records. CI uses neither credentials
nor external services: pytest runs against `MemoryRepository`, and the frontend
must lint and produce a production build.

## 3. Data model and traceability

```text
Patient 1---* TimelineEntry 1---* Comment
   |               |  \---------* Version (full snapshot)
   |               |  \---------* ProvenanceSource
   |               |                 ^
   |               \-----------------|
   |                                 |
   \---* Highlight ------------------+ (entry id + quote + offsets)
   |       |  \---* InteractionEvent (pin/highlight/edit/comment/less relevant)
   |       \------ trust, risk, confidence, score, decay explanation
   | 
   \---* Task
   \---* Conflict ---- source A pointer + source B pointer
   \---* AuditLog ---- actor/action/time/version metadata only
   \---* EntrySummary (reserved for source-backed historical compression)
```

`TimelineEntry` records author role/id, timestamp, interaction type, visibility,
content, and version. AI-scribed doctor, nurse, and patient sessions are distinct
system entry types. A `Highlight` stores category, risk and reason, extraction
confidence and reason, trust state, base/effective importance, and a provenance
pointer containing source entry, exact quote, offsets, and offset confidence.
The UI jumps from a card to that span and marks it in the timeline.

Every edit uses `expected_version`. A matching update stores a full prior
snapshot, increments the version, and emits metadata-only audit history. A stale
write receives `409 Conflict`; reverting creates a new version rather than
rewriting history. Separate entries can be edited concurrently without collision.
Comments have independent resolve state so collaboration cannot overwrite notes.

The deployed repository uses separate logical collections for users, patients,
timeline entries, provenance, highlights, comments, tasks, versions, audit logs,
interaction events, conflicts, and entry summaries. Patient/time, visibility,
ranking/trust/category, unresolved comments/tasks, revision order, and conflict
status are indexed for the demo's read patterns.

## 4. Trust, privacy, and adaptive importance

The action matrix distinguishes patient, staff, clinician, and admin operations.
All record routes check the signed actor, action permission, patient binding, and
clinic scope. Patients receive only patient-safe summaries and instructions;
raw AI transcripts, AI-scribed notes, internal comments, unreviewed signals, and
audit history are excluded. Staff cannot edit clinician sections, clinicians
cannot overwrite staff notes, and cross-clinic access is rejected.

Clinical highlight decisions form an explicit trust transition. Clinicians and
admins accept a suggestion into `clinician_confirmed` or reject it out of both
Glance and Review Queue. The reviewer, role, time, reason, and metadata-only
audit event are persisted; confirmation never overrides source visibility.

Confidence is operational rather than decorative. Extraction confidence means
how clearly a source-backed fact was extracted; provenance confidence measures
whether an entry and exact offsets resolve. Low extraction/provenance confidence
or an unresolved contradiction generates an abstention reason and review item.
Allergy, medication, high-risk symptom, and unresolved-action rules impose risk
floors which model output and user feedback cannot lower.

Adaptive importance is a bounded, explainable adjustment. Pin, highlight, edit,
and comment events increase the acted-on signal up to +12; “Less relevant” can
reduce a routine signal down to -8 and undo prior boosts. It cannot suppress a
safety signal below its deterministic baseline. The displayed reason explains
both positive and negative adjustments, reducing hidden feedback-loop behavior.
This is deliberately per-signal rather than broad category learning, limiting
exposure bias and harm from rushed dismissals.

Data decay is ranking-based in the prototype: routine information older than 180
or 365 days receives an explained reduction while its full source remains
available. Safety-critical, unresolved, conflicted, or clinician-confirmed facts
do not decay. A production extension would create source-backed `EntrySummary`
records and cold-store originals without deleting provenance or revision history.

## 5. Verification, trade-offs, and demo evidence

The required micro-tests cover server-side RBAC, patient filtering, revision and
revert behavior, metadata-only audit, resolvable highlight provenance, separate
and conflicting concurrent edits, self-learning bounds, PHI redaction, fallback
ingestion, idempotency, conflict detection, demo authentication, patient AI chat,
and audio validation. Run `pytest` in `backend`, then `npm run lint` and
`npm run build` in `frontend`.

Important trade-offs are explicit. Demo authentication is not production IAM.
PHI redaction is defense-in-depth for synthetic demonstrations, not a guarantee
for unrestricted real clinical input. Voice capture uses hosted ASR and does not
yet provide diarization, overlap recovery, word timestamps, or noisy-room quality
metrics. MongoDB multi-document transactions and durable job queues would be
needed for higher-throughput production ingestion. The current synchronous path
keeps failures visible and the safety behavior easy to inspect within 72 hours.

The judging story is a closed trust loop: open the Glance View in under ten
seconds; click an AI-derived signal to its exact source; inspect its risk,
confidence, ranking, and trust reasons; accept or reject it and explain how
source views, comments, and edits create bounded learning signals; add a staff
note with an assigned clinician comment; edit and revert a
clinician plan; review a conflict and an abstained candidate; then capture or
upload consult audio and pass its editable transcript through redaction and the
same source-backed ingestion pipeline.
