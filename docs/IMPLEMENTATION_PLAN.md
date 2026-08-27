# CareDelta Implementation Plan

## Product Direction

CareDelta is a source-backed clinical change radar for longitudinal care records.
It focuses on what changed since the last visit, what needs action, what conflicts
with prior knowledge, and what clinicians have actually trusted.

Core positioning:

> AI suggests signals. Clinicians decide what becomes trusted clinical memory.

## Confirmed Technical Stack

- Next.js with App Router
- TypeScript
- Python API backend for clinical logic, RBAC, AI ingest, provenance, and audit
- Next.js route handlers only as a lightweight BFF/proxy if needed
- MongoDB Atlas for deployed persistence
- Tailwind CSS for UI
- Pytest for backend micro-tests
- Vitest only for focused frontend/unit tests if needed
- GitHub Actions for CI
- Vercel for the Next.js frontend
- Python backend deployment target to be selected during implementation
- DeepSeek `deepseek-v4-flash` for real LLM ingest

## Architecture

```text
Browser UI
  |
  v
Next.js App Router
  - Patient record pages
  - Role preview UI
  - Clinical Change Radar UI
  - Timeline / comments / revisions UI
  |
  v
Optional Next.js BFF / proxy route handlers
  - session/auth forwarding
  - simple frontend aggregation
  - no source-of-truth RBAC decisions
  |
  v
Python API Backend
  - auth_context
  - rbac
  - timeline_service
  - highlight_service
  - revision_service
  - ai_ingest_service
  - delta_engine
  - phi_redaction
  - learning_engine
  - audit_log_service
  |
  v
Repository Layer
  - MongoRepository for deployed app
  - MemoryRepository for tests
  |
  v
MongoDB Atlas
```

## Deployment Strategy

The frontend will be deployed as a Next.js project on Vercel. The backend is
planned as a Python API service so clinical logic, micro-tests, extraction,
redaction, and audit behavior can be implemented in one backend boundary.

Runtime persistence:

```text
Vercel Next.js frontend -> Python API backend -> MongoDB Atlas
```

Selected delivery pipeline:

- GitHub Actions is the platform-independent quality gate for pushes and pull
  requests to `development` and `main`.
- The FastAPI backend is packaged as a non-root Docker image and deployed as a
  persistent Railway service from the `/backend` monorepo root.
- The Next.js frontend is deployed from `/frontend` on Vercel to retain native
  Next.js builds and automatic pull-request preview deployments.
- Vercel Development and Preview environments call
  `https://caredelta-development.up.railway.app`; Vercel Production calls
  `https://caredelta-production.up.railway.app`.
- Railway and Vercel GitHub autodeploys must deploy production from `main` only.
- Railway `Wait for CI` must be enabled so a failing GitHub check prevents the
  backend deployment. Branch protection on `main` should require both CI jobs.
- Deployment credentials live only in platform environment-variable stores.
  GitHub Actions intentionally runs against `MemoryRepository` without external
  service secrets.
- The Railway `/health` check gates backend rollout. The frontend production
  build is the Vercel deployment gate.

If implementation time becomes tight, a Next.js-only backend remains a fallback.
The preferred direction is Python backend plus Next frontend because the required
micro-tests are backend-heavy and Python gives faster iteration for redaction,
structured extraction, and pytest-based safety tests.

### Vercel Runtime Constraints

- Next.js route handlers must not become the source of truth for RBAC.
- If a Next.js BFF is used, it forwards to the Python API and preserves actor
  role, clinic scope, and request id.
- The Python backend must reuse MongoDB clients rather than opening a new
  connection per request.
- Keep the demo AI ingest path short and synchronous for 72-hour delivery.
- Treat long transcripts as a future async job design, not the core demo path.
- The main patient record page must load from precomputed records and highlights;
  it must not call the LLM on page load.

## Test Strategy

GitHub Actions will run:

```text
python -m pytest
npm ci
npm run build
```

Tests must not depend on MongoDB Atlas, DeepSeek, Vercel, or any external API.
They will run against `MemoryRepository` and mock LLM adapters.

The required micro-tests from the candidate brief will be implemented as Python
pytest equivalents:

- `tests/test_rbac_scope.py`
- `tests/test_revision_history.py`
- `tests/test_highlight_provenance.py`
- `tests/test_concurrent_edits.py`
- `tests/test_self_learning_importance.py`

The repository layer should expose a shared contract test suite:

- CI runs the contract tests against `MemoryRepository`.
- Local development may optionally run the same contract tests against
  `MongoRepository` when `MONGODB_URI` is present.
- This keeps CI stable while still making the Mongo implementation verifiable.

## LLM Integration

DeepSeek `deepseek-v4-flash` will be integrated through an adapter interface.

LLM pipeline:

```text
Raw synthetic transcript
  -> PHI redaction
  -> DeepSeek adapter
  -> structured JSON validation
  -> delta engine
  -> highlights with provenance
```

Rules:

- Raw transcript must not be sent to the LLM before PHI redaction.
- DeepSeek output is treated as candidate signals, not clinical truth.
- The backend delta engine owns final category, score, and trust status.
- Provenance is created by locating LLM/rule `source_snippet` values inside the
  sanitized transcript, then storing entry id and character offsets.
- If DeepSeek fails or returns invalid JSON, the app falls back to a deterministic
  rule-based extractor.
- Tests use a mock LLM adapter.

Environment variables:

```text
DEEPSEEK_API_KEY
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL
MONGODB_URI
```

Secrets must not be committed.

### LLM JSON Contract

DeepSeek must return JSON only. Natural language output is invalid and triggers
the deterministic fallback extractor.

Expected shape:

```py
class LlmSignal(TypedDict):
    text: str
    category_hint: Literal[
        "new",
        "worsening",
        "recurring",
        "unresolved",
        "contradicted",
        "confirmed",
    ]
    risk_level_hint: Literal["low", "medium", "high"]
    risk_reason: str
    source_snippet: str
    entities: list[str]
    extraction_confidence: float


class LlmExtraction(TypedDict):
    summary: str
    signals: list[LlmSignal]
```

Validation rules:

- `source_snippet` is required for every signal.
- `extraction_confidence` must be between 0 and 1.
- Signals without resolvable provenance are downgraded to entry-level provenance
  and marked `offsetConfidence: "low"`.
- The LLM must not diagnose, invent facts, or convert patient claims into
  confirmed clinical facts.

## Evaluation and Abstention Policy

Risk badges, confidence labels, and importance scores must be explainable and
testable. They are not allowed to be decorative model outputs.

Implementation approach:

- Treat `extraction_confidence` as confidence that the extractor found a
  source-backed signal, not confidence that the clinical statement is true.
- Track separate provenance confidence:
  - `high`: exact source snippet resolves to entry and character span.
  - `medium`: snippet resolves to an entry but not exact offsets.
  - `low`: only entry-level provenance is available.
- Use deterministic safety rules to set a minimum risk floor for scoped clinical
  classes such as allergies, medication changes, dosage changes, and unresolved
  follow-up tasks.
- The LLM may suggest risk, but the backend delta engine owns the final category,
  risk floor, trust status, and whether the signal is displayable.
- Abstain from promoting a signal into the top/glance card when provenance cannot
  resolve, extraction confidence is below threshold, or the statement conflicts
  with trusted memory and has not been reviewed.
- Low-confidence or conflicting signals can still appear in a review queue with
  a clear reason, but they must not be shown as confirmed clinical memory.

## Patient-Facing Safety Gate

Patient-facing summaries and instructions are a higher-severity output path than
internal notes.

Implementation approach:

- Patients never see raw AI-scribed notes, raw transcripts, internal comments, or
  unreviewed AI candidate signals.
- Patient-facing content must be assembled from clinician-approved entries,
  explicit patient instructions, or rule-filtered safe summaries.
- Conflicting, low-provenance, rejected, or unreviewed highlights are excluded
  from patient view.
- Any patient-facing generated summary must carry an approval status. For the
  72-hour demo, the safest implementation is to require clinician approval before
  it becomes visible to the patient role.

## Scoped Conflict Detection

Conflict detection will be deliberately narrow for the demo so it is testable.

Implementation approach:

- Detect allergy conflicts where one entry states an allergy and a later entry
  denies or contradicts it.
- Detect medication conflicts for medication name, dose, or frequency changes.
- Detect task-state conflicts such as an item marked resolved while another open
  action still depends on it.
- Clinician-authored entries take precedence for care-plan display, but conflicts
  are still flagged for review instead of silently overwriting history.
- Store conflict records with both source pointers so the reviewer can jump to
  the competing entries.

## Self-Learning Guardrails

The importance learning mechanism must learn from clinical attention without
creating an unsafe feedback loop.

Implementation approach:

- Manual highlight, pin, edit, and comment events can boost similar future
  signals.
- Learning is a bounded boost, not the whole importance score.
- Dismissal does not automatically mean a class of information is clinically
  unimportant; it is recorded as context, not negative truth.
- Deterministic safety floors for allergies, medication changes, high-risk
  symptoms, and unresolved tasks cannot be reduced by learned weights.
- Store the reason for each learned boost, such as `boosted_by_prior_pins` or
  `boosted_by_clinician_comments`, so the ranking can be explained in the demo.

## Hybrid Storage and Data Decay

Hybrid storage/data decay is a bonus feature. It should be designed even if only
partially implemented.

Implementation approach:

- Keep recent timeline entries, unresolved tasks, active medication/allergy
  facts, and conflicted records in full detail.
- Older low-risk entries can be compressed into source-backed longitudinal
  summaries.
- Compression must preserve links to the original entries and must not destroy
  revision history.
- Safety-critical facts, unresolved tasks, clinician-confirmed highlights, and
  conflicts never decay into summary-only storage.
- The demo can show this as a policy and seed-data example rather than a full
  background compaction job.

### PHI Redaction Contract

PHI redaction runs before the DeepSeek adapter.

Redacted fields:

- synthetic patient names
- phone numbers
- NRIC-like or ID-like values
- email addresses
- simple address patterns when present

Tests must assert that the LLM adapter never receives known synthetic names,
phone numbers, IDs, or emails from the seed transcript.

## MongoDB Data Strategy

Use separate collections rather than one large patient document:

- `users`
- `patients`
- `timeline_entries`
- `provenance_sources`
- `highlights`
- `comments`
- `tasks`
- `versions`
- `audit_logs`
- `interaction_events`
- `conflicts`
- `entry_summaries`

Required indexes:

- `patients`: `{ clinicId: 1 }`
- `timeline_entries`: `{ patientId: 1, timestamp: -1 }`
- `timeline_entries`: `{ patientId: 1, visibilityScope: 1 }`
- `highlights`: `{ patientId: 1, score: -1, trustStatus: 1, category: 1 }`
- `comments`: `{ entryId: 1, resolved: 1 }`
- `tasks`: `{ patientId: 1, status: 1, dueAt: 1 }`
- `versions`: `{ entryId: 1, versionNumber: -1 }`
- `audit_logs`: `{ patientId: 1, createdAt: -1 }`
- `interaction_events`: `{ patientId: 1, extractedTopic: 1, createdAt: -1 }`
- `conflicts`: `{ patientId: 1, status: 1, severity: -1 }`
- `entry_summaries`: `{ patientId: 1, sourceEntryIds: 1 }`

### Consistency Strategy

AI ingest writes multiple records: provenance source, timeline entry, highlights,
and audit log.

Preferred implementation:

- Use MongoDB session transactions when available.
- If transactions are not available in the local/dev setup, use ordered writes
  and delete newly created dependent records if a later step fails.
- Never create a highlight without a valid `provenancePointer`.
- Never write audit logs containing raw note or transcript body.

## RBAC Action Matrix

All checks must run on the server in route handlers or service methods. UI hiding
is only presentation logic.

```text
Action                         Patient   Staff   Clinician   Admin
read_patient_summary           yes       yes     yes         yes
read_patient_instructions      yes       yes     yes         yes
read_staff_notes               no        yes     yes         yes
read_clinician_sections        no        no      yes         yes
read_raw_ai_transcript         no        no      yes         yes
read_internal_comments         no        yes     yes         yes
create_staff_note              no        yes     no          yes
edit_staff_note                no        own     no          yes
edit_clinician_section         no        no      yes         yes
create_internal_comment        no        yes     yes         yes
accept_highlight               no        no      yes         yes
reject_highlight               no        no      yes         yes
pin_highlight                  no        no      yes         yes
rollback_entry                 no        no      owner-role  yes
read_audit_log                 no        no      yes         yes
```

Every action also requires same-clinic scope unless the actor is a scoped admin
for that clinic. There is no cross-clinic access in the demo.

## Revision and Concurrency Strategy

Use optimistic concurrency.

- Every editable timeline entry has a numeric `version`.
- Edit requests must include `expectedVersion`.
- If `expectedVersion` does not match the stored version, return `409 Conflict`.
- Different roles editing different entries do not overwrite each other.
- Staff cannot overwrite clinician entries, and clinicians cannot overwrite staff
  entries; they can comment, reference, or create their own entry.
- Rollback never deletes history. It creates a new version whose content matches
  the selected prior snapshot.

## Performance Plan

The brief requires the top consult view to load within P95 <= 300ms on the hot
path.

Implementation approach:

- Precompute highlights during AI ingest and manual entry updates.
- Store radar-ready highlights in the `highlights` collection.
- Patient record load performs indexed reads only:
  - patient profile
  - top highlights
  - unresolved tasks
  - recent timeline entries
- Do not call DeepSeek or run full delta analysis during page load.
- Measure locally by logging route duration for `GET /api/patients/[id]/record`.
- Document the measurement as a local hot-path estimate in the technical brief.

## Failure Modes and Fallbacks

- DeepSeek timeout: use deterministic rule extractor and mark extraction source
  as `fallback_rules`.
- Invalid DeepSeek JSON: reject the LLM response, use fallback extractor, and log
  metadata only.
- `source_snippet` not found: create entry-level provenance with
  `offsetConfidence: "low"`.
- Mongo write failure during AI ingest: rollback dependent writes where possible;
  do not leave orphan highlights.
- Missing environment variables in production: show a clear setup error for
  ingest, but allow seeded read-only demo pages to load when possible.
- Patient attempts restricted access: return filtered response or `403`,
  depending on endpoint semantics.

## Core Differentiators

1. It does not summarize everything. It finds what changed.
2. AI never becomes truth without clinical confirmation.
3. Every signal is clickable back to its source.
4. Recency matters, but clinical significance overrides recency.
5. The system learns from clinical attention, not hidden assumptions.

## Update Rule

Any new implementation decision, product idea, scope tradeoff, or architecture
change discussed during the build should be added to this document so the final
README and technical brief stay consistent with the actual implementation.

## Implementation Status

### Phase 1: Project Skeleton

- Added a FastAPI application under `backend/` with `GET /health`.
- Added environment-based backend configuration and local CORS access for the
  Next.js origin.
- Added a Python health endpoint micro-test using FastAPI's test client.
- Added a Next.js App Router application under `frontend/` using TypeScript and
  Tailwind CSS.
- The initial page performs a browser-side health request using
  `NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8000`, and renders the
  connection state explicitly.
- Local setup, run, test, lint, and build commands are documented in `README.md`.
- Production builds use Next.js Webpack mode for deterministic compatibility
  with restricted CI environments; local development continues to use the
  default fast development bundler.
- MongoDB, RBAC, clinical services, provenance, and LLM integration remain out
  of scope for Phase 1 and are not yet implemented.

### Phase 2: Core Models and Synthetic Record

- Added Pydantic domain models for `Patient`, `TimelineEntry`, `Highlight`,
  `ProvenancePointer`, `Comment`, `Task`, `Version`, `AuditLog`,
  `InteractionEvent`, and `Conflict`.
- Added a repository protocol and an in-process `MemoryRepository`. It returns
  defensive copies so API consumers cannot mutate repository state by reference.
- Added a deterministic synthetic record for `patient-syn-001`, including
  clinician, staff, patient, and AI-scribed timeline entries across multiple
  dates.
- Added `GET /api/patients/{patient_id}/record` as the Phase 2 aggregate read
  endpoint. It returns precomputed highlights and tasks with the complete linked
  record needed by the patient page.
- Local CORS accepts both `localhost:3000` and `127.0.0.1:3000`, in addition to
  the configured frontend origin, so browser-based development works with either
  standard loopback hostname.
- Every seeded highlight has an exact `ProvenancePointer` with entry ID, source
  quote, and character offsets. Automated tests assert that every pointer resolves
  back to the exact timeline span.
- The frontend now renders a 10-second glance card, open actions, conflict state,
  comments, and the longitudinal timeline. Selecting a highlight scrolls to and
  marks its precise source span.
- Phase 2 intentionally does not implement persistence, mutation endpoints,
  server-side RBAC enforcement, or real AI ingest. Those remain subsequent-phase
  work and the current seed resets whenever the FastAPI process restarts.

### Phase 3: RBAC and Role Preview

- Added explicit `patient`, `staff`, `clinician`, and `admin` user roles, kept
  separate from the `system` content-author role.
- Added a server-side action matrix matching the documented read, write,
  highlight, audit, comment, and rollback permissions.
- Every patient read and mutation now requires an actor ID, role, and clinic ID;
  all four roles, including admin, are rejected outside their clinic scope.
- Patient-record responses are filtered server-side. Hidden entries also remove
  dependent highlights, tasks, comments, versions, audit events, interactions,
  and conflicts so provenance cannot leak restricted note content.
- Patients receive only patient-authored summaries and clinician-approved
  patient instructions; raw AI notes, internal comments, audit records, and
  unreviewed highlights are excluded.
- Added server-authorized create and edit endpoints for staff notes and clinician
  sections. Staff can edit only their own staff notes; clinicians cannot overwrite
  staff notes; staff cannot create or edit clinician sections; scoped admins can
  manage either.
- The frontend role switcher is explicitly a demo preview. It sends mock auth
  headers, but the backend independently enforces every permission. Production
  must replace these headers with verified session or signed-token claims.
- Added `tests/test_rbac_scope.py` covering patient data filtering, staff read
  filtering, forbidden cross-role writes, staff ownership, required auth context,
  and clinic isolation for all four roles.

### Phase 4: Timeline and Collaboration

- Timeline entries are returned newest-first across patient, staff, clinician,
  and AI/system sources after server-side role filtering.
- Staff and clinicians create notes in distinct protected sections; existing
  ownership rules continue to prevent cross-role overwrites.
- Internal comments support `mentions`, an optional `assigned_role`, and an
  explicit resolved/unresolved status without mutating the source note.
- Comment creation and status updates enforce the action matrix, clinic scope,
  and visibility of the referenced timeline entry.
- The demo UI supports the complete staff-to-clinician handoff: publish a staff
  note, mention and assign a clinician, switch roles, then resolve or reopen it.

### MongoDB Atlas Persistence

- Application runtimes now require `MONGODB_URI` and use `MongoRepository`;
  automated backend tests continue to override it with an isolated
  `MemoryRepository` and do not require network access or secrets.
- `MONGODB_DATABASE` separates `caredelta_development` from
  `caredelta_production` while keeping the connection URI independent of the
  environment-specific database name.
- Backend startup pings Atlas, creates unique patient and query indexes, and
  inserts the synthetic patient through `$setOnInsert`, making initialization
  safe across repeated deployments.
- Timeline creation, comments, assignment status, and resolve/unresolve persist
  in the patient aggregate document. Timeline edits use an atomic entry ID plus
  `expected_version` match and write revision/audit data in the same update.
- A live development-Atlas check confirmed one idempotent seed document, five
  timeline entries, successful model hydration, and all configured indexes.

### Phase 5: Revision History and Revert

- New editable notes create a complete version 1 snapshot; every edit atomically
  increments the entry version and appends the complete resulting note snapshot.
- Revert accepts a target version plus `expected_version`, restores the selected
  snapshot, and appends a new higher version rather than changing old history.
- Stale edits and reverts return `409 Conflict` through the same optimistic
  concurrency boundary in `MemoryRepository` and `MongoRepository`.
- Revision history has its own read action for staff, clinician, and admin roles;
  entry visibility and existing ownership rules still constrain edit and revert.
- Audit logs contain action, actor, entity, changed-field names, timestamps, and
  request IDs only. Raw current, previous, and reverted note bodies live solely
  in protected version snapshots, never in audit metadata.
- The timeline UI offers role-authorized editing, a previous/current comparison,
  complete version metadata, and explicit revert controls.

### Phase 6: Provenance and Highlight Jump

- `ProvenancePointer.offset_confidence` is now a constrained high/medium/low
  value, not an arbitrary string.
- Every seeded highlight stores a pointer to its source timeline entry, source
  quote, source metadata, and exact character span.
- `tests/test_highlight_provenance.py` verifies that every returned highlight
  resolves to the exact timeline substring and that Scenario A uses the reliever
  highlight to jump to the patient check-in source span.
- The glance card displays provenance confidence. Clicking a highlight scrolls
  to the source timeline entry, marks the supporting text span, and displays the
  confidence beside the source label.

### Phase 7: AI Ingest and PHI Redaction

- Added a clinician/admin-only AI ingest endpoint with the same clinic-scope and
  server-side action enforcement as the rest of the patient record.
- Added a protected redaction-preview endpoint. The frontend displays the exact
  sanitized payload and detected PHI categories before enabling ingest, while
  the ingest endpoint independently repeats redaction and never trusts the
  preview result.
- The backend redacts the known patient name, email, phone, and common patient
  or medical ID formats before invoking any LLM adapter. The sanitized text is
  also the stored AI-scribed source so provenance offsets cannot point into PHI.
- PHI handling is a layered local pipeline: Python `phonenumbers` with Singapore
  metadata detects compact, spaced, dashed, and international phone formats;
  contextual patterns detect self-introduced, labelled, and honorific-prefixed
  names even when they differ from the patient profile; structured rules cover
  email and NRIC/medical IDs. No external PII service sees the transcript.
- Added an OpenAI-compatible DeepSeek adapter configured by base URL, model, API
  key, and timeout. The adapter requests JSON-only output and validates it using
  a strict Pydantic contract with unknown fields rejected.
- DeepSeek extraction explicitly disables the model's default high-effort
  thinking mode, caps output at 1,200 tokens, and uses a 30-second timeout. This
  keeps structured extraction responsive while retaining deterministic fallback
  for genuine service failures. A live synthetic, non-persistent probe returned
  through the `deepseek` path with two validated source-grounded signals.
- Model signals without an exact `source_snippet` in the sanitized transcript
  are rejected. Network, timeout, response-shape, JSON, and grounding failures
  converge on a deterministic keyword-based extractor that emits up to five
  reviewable, source-grounded signals.
- Successful and fallback ingestion atomically append a clinician-visible
  interaction-specific system entry, full version snapshot, metadata-only audit
  event, and one or more `ai_suggested` highlights with exact provenance
  pointers. Supported entry types are doctor consult, nurse consult, and patient
  session summaries.
- Added the complete clinician/admin ingest panel: interaction selection,
  transcript and source inputs, redaction warning/preview, Run ingest action,
  extraction summary, DeepSeek/fallback indicator, and explicit timeout,
  invalid-JSON, unavailable-LLM, and unresolved-provenance states. Successful
  ingest refreshes timeline and glance data and focuses the new source entry.
- `tests/test_ai_ingest.py` uses mock adapters and `MemoryRepository` to prove
  that name, phone, ID, and email values never reach the adapter; invalid JSON,
  timeouts, and ungrounded provenance trigger fallback; every generated signal
  resolves to a stored system entry span; and raw transcript content is absent
  from audit metadata. The integration test covers preview, ingest, aggregate
  reload, system entry visibility, and highlight-to-source resolution.
- The reported `Tan Mei Ling` / Singapore local-phone failure case is a permanent
  regression fixture. It asserts that name, NRIC, local phone, and email are
  absent from both preview and mock-adapter input while medication doses remain
  intact; additional parametrized tests cover common Singapore phone formats.
- AI ingest now uses `interaction_type + source_id` as its idempotency key.
  Existing Mongo records are backfilled with keys during initialization, normal
  duplicates are rejected before an LLM call, and the Mongo write independently
  applies the same key as an atomic condition to prevent concurrent duplicates.
- The 10-second glance uses backend pagination with three highlights per page.
  Ranking is strictly importance score first and recency second, keeping the
  first page fast to scan while allowing clinicians to browse every lower-ranked
  signal through compact previous/next controls with the current page indicator.
  Timeline history remains intact.
