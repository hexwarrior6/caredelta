# CareDelta

**A source-backed clinical change radar for safer handoffs.**

- **Live demo:** [caredelta-frontend.vercel.app](https://caredelta-frontend.vercel.app)
- **Technical brief:** [`docs/TECHNICAL_BRIEF.md`](docs/TECHNICAL_BRIEF.md)
- **External attribution:** [`ATTRIBUTION.txt`](ATTRIBUTION.txt)

Clinical records are rich in detail but poor at showing change. Important
symptoms, unresolved actions, contradictions, and patient context are often
spread across dated notes written by different people. CareDelta turns that
fragmented history into a shared longitudinal record focused on one question:

> What changed, why does it matter, and where is the evidence?

CareDelta does not try to summarize everything. It surfaces the signals that
need attention, connects each one to its exact source, and keeps the clinician
in control of what becomes trusted clinical memory.

## Product principles

- **Source before assertion:** every important signal links back to its timeline
  entry and supporting text.
- **AI suggests; clinicians decide:** generated signals remain candidates until
  reviewed and trusted by the care team.
- **Change over chronology:** the glance view prioritizes new, worsening,
  recurring, unresolved, contradicted, and confirmed information.
- **Action over information overload:** open tasks and clinically meaningful
  changes should be readable within seconds.
- **History is preserved:** comments, revisions, audit metadata, and conflicts
  remain traceable rather than being silently overwritten.

## What the application provides

- A concise top/glance card for high-priority clinical changes
- A longitudinal timeline containing patient, staff, clinician, and AI-scribed
  entries
- Shared staff and clinician notes with internal comment threads
- Lightweight `@clinician` mentions, role assignment, and resolvable handoffs
- Immutable full-snapshot revision history with previous/current comparison
- Optimistic-concurrency editing and revert-as-a-new-version recovery
- Exact provenance pointers from highlights to their source text, including
  high/medium/low confidence
- PHI-redacted DeepSeek ingestion with strict JSON validation and a deterministic
  rule-based fallback
- Open care-team tasks, comments, revision snapshots, and audit metadata
- Explicit conflict records for information that requires reconciliation
- Server-enforced role and clinic boundaries for patient, staff, clinician, and
  admin access
- A passwordless demo landing page with three synthetic patients and dedicated
  staff, clinician, and admin identities
- A PHI-redacted patient AI assistant whose saved conversations can be promoted
  into source-backed patient-session timeline entries
- Browser microphone/upload capture backed by Volcengine BigModel flash ASR,
  feeding the same redaction, extraction, provenance, and review pipeline
- Deterministic synthetic data for safe local development and demonstration

Application runtimes persist patient records in MongoDB Atlas through
`MongoRepository`. Local development and Railway use separate database names,
while automated tests override the repository with an isolated
`MemoryRepository` so CI remains deterministic and requires no external secret.

## Architecture

```text
Browser
  -> Next.js App Router + TypeScript + Tailwind CSS
  -> FastAPI clinical API
  -> Repository interface
  -> MongoRepository -> MongoDB Atlas (application runtime)
  -> MemoryRepository (automated tests only)
```

The frontend renders the care record, while the Python backend owns clinical
logic, access control, provenance, audit behavior, and AI ingestion.

## Local development

### Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+

### Environment configuration

```bash
cp backend/.env.example backend/.env.local
cp backend/.env.production.example backend/.env.production
cp frontend/.env.development.example frontend/.env.development
cp frontend/.env.production.example frontend/.env.production
```

Use `backend/.env.local` for local development. `backend/.env.production` is an
ignored local reference for production values and can be loaded locally with
`CAREDELTA_ENV_FILE=.env.production`; Railway itself must receive the same values
through its Variables settings. Replace all credential placeholders and never
commit either real environment file.

Set `MONGODB_DATABASE=caredelta_development` locally and in Railway development.
Use `MONGODB_DATABASE=caredelta_production` in Railway production so synthetic
development activity cannot modify production records. On startup, the backend
checks Atlas connectivity, creates indexes, and inserts the synthetic seed only
when that patient does not already exist.

### Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is available at [http://localhost:8000](http://localhost:8000), with
interactive documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

### Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Choose one of the six demo
identities and use its automatically filled access key. Patient identities open
only their own records; care-team identities can switch among the three
synthetic patient workspaces. Logging out clears the local session and returns
to the landing page. Select a signal in the
glance card to jump to and highlight its supporting text in the timeline. The
source marker shows the provenance confidence carried by the backend pointer.
Sign in as staff to add a note and assign an `@clinician` comment, then log out
and sign in as the clinician to resolve or reopen the handoff.

Patient identities also have an **Ask about your care** workspace. Each question
is redacted locally in the backend before it is sent to DeepSeek, and the
redacted patient/assistant exchange is stored with that patient's record. The
patient must explicitly choose **Add to record** before the conversation creates
a timeline entry. At that point the existing ingest pipeline extracts candidate
signals only from patient-authored statements, creates exact provenance
pointers, and routes untrusted signals to care-team review; AI assistant wording
is never treated as a patient clinical fact.

All demo roles can also open **Capture consult** from the timeline. The browser
can record microphone audio with `MediaRecorder` or upload an existing audio
file (up to 15 MB). Audio is sent with the signed CareDelta session to the
backend, which calls Volcengine BigModel flash ASR server-side; ASR credentials
are never exposed to the browser. The returned transcript remains editable and
must pass the existing redaction preview before DeepSeek/fallback extraction and
timeline ingestion. Patient and staff interaction types are constrained by the
backend to patient-session and nurse-consult flows respectively.

## API

Check service health:

```bash
curl http://localhost:8000/health
```

Fetch the complete synthetic patient record:

```bash
TOKEN=$(curl -s http://localhost:8000/api/demo/login \
  -H "Content-Type: application/json" \
  -d '{"identity_id":"clinician-syn-lim","demo_key":"CLINICIAN-DEMO-2026"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/patients/patient-syn-001/record
```

The patient-record response includes the patient, highlights, provenance
pointers, tasks, timeline entries, comments, versions, audit logs, interaction
events, and conflicts.

Each highlight includes a `provenance_pointer` with the source timeline entry,
source quote, character offsets, source metadata, and a high/medium/low
confidence value. The frontend uses this pointer to scroll from the glance card
to the supporting timeline entry and mark the exact span.

Staff, clinician, and admin views can create role-appropriate notes and internal
comments through the timeline. Comment status is updated independently from the
source note so collaboration never overwrites clinical content.

Editable notes expose their revision history in the timeline. Every edit creates
a complete snapshot with an incremented version. Reverting restores a selected
snapshot by creating another version, so historical states are never deleted or
rewritten. Audit logs retain metadata only and never store raw note bodies.

### AI-scribed note ingestion

Clinician and admin roles can submit a transcript to
`POST /api/patients/{patient_id}/ai-ingest`. Before any model call, the backend
replaces the known patient name, email addresses, phone numbers, and common
patient/medical ID formats. Only this sanitized transcript is sent to the
OpenAI-compatible DeepSeek endpoint.

Phone detection runs locally with Python `phonenumbers` and Singapore-region
metadata, covering compact, spaced, dashed, and `+65` formats without sending
text to another service. A contextual name layer additionally removes names in
phrases such as `my name is`, `patient name`, and common clinician/nurse
honorifics, including names which differ from the patient profile. Structured
email and NRIC/medical-ID rules remain in the same local pipeline.

The clinician/admin timeline includes an **Ingest AI note** panel for doctor
consultations, nurse consultations, and patient sessions. A separate redaction
preview request shows the exact sanitized text and detected PHI types before the
Run ingest action is enabled. The backend repeats redaction during the actual
ingest so the security boundary never depends on browser state.

DeepSeek must return the server-defined JSON contract and every proposed signal
must quote an exact substring of the sanitized transcript. Malformed JSON,
timeouts, network failures, or source-less signals automatically use the local
deterministic rule extractor. Both paths create a clinician-visible system
timeline entry and source-backed, `ai_suggested` highlights. The result panel
shows whether DeepSeek or fallback produced the result, including timeout,
invalid JSON, unavailable LLM, or unresolved provenance reasons. Timeline and
glance data refresh immediately, and generated highlights retain the existing
click-to-source behavior. No API key is required by automated tests; they inject
mock adapters and isolated memory data.

The ingest form starts empty. The source/session identifier is generated
automatically and kept out of the clinical UI, while DeepSeek produces the
timeline title as part of the same structured extraction. If the LLM path is
unavailable, the deterministic extractor supplies a stable title from the
highest-priority source-backed signal.

The 10-second glance shows three backend-ranked highlights per page. Signals are
sorted by importance score and then recency, so clinicians see the most urgent
changes first while retaining access to lower-ranked pages. AI ingest is
idempotent by interaction type plus source ID; duplicate or concurrent
submissions return `409 Conflict` before creating another timeline entry or
highlight set.

CareDelta's Delta Engine classifies longitudinal change as new, worsening,
recurring, unresolved, contradicted, or confirmed. It applies deterministic
risk floors and recomputes importance from risk, category, and extraction
confidence. Low-confidence or conflicting signals abstain from the glance card
and remain source-backed in a clinician review queue, with plain-language
explanations for risk, confidence, and ranking.

Clinicians and clinic admins can accept or reject suggestions from either the
glance card or review queue. Accepting records a named clinical review and moves
the signal to `clinician_confirmed`; rejecting removes it from both the glance
card and review queue. Every decision persists reviewer, role, timestamp, and
reason with a metadata-only audit event. Confirmation never bypasses source
visibility: a patient can see a confirmed signal only when its source entry is
already patient-visible.

The radar learns conservatively from clinician behavior. Pins, comments, edits,
and source highlights update one per-user net learning adjustment capped at
+12; explicit “Less relevant” feedback subtracts from that same value, down to
-8 for routine signals. Safety signals stop at zero, so negative feedback can
undo a prior boost without lowering them below baseline. Explanations include `boosted_by_prior_pins` and
`reduced_by_less_relevant_feedback`. Feedback never rewrites clinical risk, and
negative learning is ignored for safety signals. Allergy, medication, and open-task conflicts are placed
in review with both sources preserved. Routine old signals receive bounded data
decay, while high-risk, contradicted, and unresolved safety information is
exempt from age-based downgrading.

## Access control

The backend enforces an action matrix for `patient`, `staff`, `clinician`, and
`admin`, and every patient operation is restricted to the actor's clinic. The
landing page exposes synthetic identities and prefilled keys for a frictionless
demo, but login is still checked by the API and returns an expiring HMAC-signed
bearer session. A patient token is bound to exactly one patient ID; changing the
browser URL cannot expose another record. The frontend switcher is navigation
only and is never an authorization source. Legacy identity headers are disabled
at runtime and enabled only inside isolated automated tests.

## Quality checks

Backend tests:

```bash
cd backend
source .venv/bin/activate
pytest
```

Frontend lint and production build:

```bash
cd frontend
npm run lint
npm run build
```

GitHub Actions runs the same backend and frontend checks for pushes and pull
requests targeting `development` or `main`. The workflow does not require
MongoDB, DeepSeek, Railway, or Vercel credentials.

## Deployment

The recommended deployment topology is:

```text
GitHub pull request
  -> GitHub Actions: backend tests + frontend lint/build
  -> merge to main
     -> Railway: FastAPI backend
     -> Vercel: Next.js frontend
```

### Railway backend

Create a Railway service from this GitHub repository with:

- Root Directory: `/backend`
- Builder: Dockerfile
- Healthcheck Path: `/health`
- Production branch: `main`
- Wait for CI: enabled

Set these Railway variables without committing their values:

- `MONGODB_URI`
- `MONGODB_DATABASE` — `caredelta_development` or `caredelta_production`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_TIMEOUT_SECONDS` — optional; defaults to `30`
- `DEEPSEEK_MAX_TOKENS` — optional; defaults to `1200`
- `CAREDELTA_FRONTEND_ORIGIN` — the production Vercel URL
- `CAREDELTA_FRONTEND_ORIGIN_REGEX` — optional, tightly scoped preview URL regex
- `DEMO_AUTH_SECRET` — long random secret used to sign demo sessions
- `ALLOW_LEGACY_AUTH_HEADERS` — keep `false` outside automated tests
- `VOLCENGINE_API_KEY` — server-side Volcengine Speech API key
- `VOLCENGINE_ASR_URL` — optional BigModel flash endpoint override
- `VOLCENGINE_ASR_TIMEOUT_SECONDS` — optional; defaults to `45`

Generate a public Railway domain after the deployment passes its health check.

### Vercel frontend

Import the same GitHub repository into Vercel with:

- Root Directory: `frontend`
- Framework Preset: Next.js
- Production branch: `main`
- Development/Preview `NEXT_PUBLIC_API_URL`:
  `https://caredelta-development.up.railway.app`
- Production `NEXT_PUBLIC_API_URL`:
  `https://caredelta-production.up.railway.app`

Vercel creates preview deployments for pull requests and production deployments
from `main`. Keep production and preview variables separate. Preview pages that
call the Railway API must have their origins explicitly allowed by the backend;
do not use an unrestricted wildcard origin.

## Safety

CareDelta is currently developed and demonstrated with synthetic data only. Do
not enter real patient information. AI-derived content must be redacted before
external model processing, treated as an untrusted candidate signal, and
reviewed before it can become patient-facing or trusted clinical memory.
