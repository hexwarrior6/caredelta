# CareDelta

**A source-backed clinical change radar for safer handoffs.**

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
- Exact provenance pointers from highlights to their source text
- Open care-team tasks, comments, revision snapshots, and audit metadata
- Explicit conflict records for information that requires reconciliation
- Server-enforced role and clinic boundaries for patient, staff, clinician, and
  admin access
- Deterministic synthetic data for safe local development and demonstration

The application currently uses an in-process `MemoryRepository`. Restarting the
backend restores the synthetic record. MongoDB persistence, production RBAC,
and live AI ingest are designed as backend responsibilities and can be added
without changing the patient-record interface.

## Architecture

```text
Browser
  -> Next.js App Router + TypeScript + Tailwind CSS
  -> FastAPI clinical API
  -> Repository interface
  -> MemoryRepository (local) / MongoDB Atlas (deployment target)
```

The frontend renders the care record, while the Python backend owns clinical
logic, access control, provenance, audit behavior, and future AI ingestion.

## Local development

### Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+

### Environment configuration

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Replace placeholder values in `backend/.env` when using MongoDB or DeepSeek.
Never commit real credentials.

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

Open [http://localhost:3000](http://localhost:3000). Select a signal in the
glance card to jump to and highlight its exact supporting text in the timeline.

## API

Check service health:

```bash
curl http://localhost:8000/health
```

Fetch the complete synthetic patient record:

```bash
curl \
  -H "X-Actor-Id: clinician-syn-lim" \
  -H "X-Actor-Role: clinician" \
  -H "X-Clinic-Id: clinic-syn-orchard" \
  http://localhost:8000/api/patients/patient-syn-001/record
```

The patient-record response includes the patient, highlights, provenance
pointers, tasks, timeline entries, comments, versions, audit logs, interaction
events, and conflicts.

## Access control

The backend enforces an action matrix for `patient`, `staff`, `clinician`, and
`admin`, and every patient operation is restricted to the actor's clinic. The
local demo sends mock identity claims through `X-Actor-Id`, `X-Actor-Role`, and
`X-Clinic-Id`; a production deployment must replace this transport with verified
session or token claims.

The role switcher in the frontend is a preview tool. It requests a role-filtered
record from the backend and is never treated as an authorization decision.

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
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_API_KEY`
- `CAREDELTA_FRONTEND_ORIGIN` — the production Vercel URL
- `CAREDELTA_FRONTEND_ORIGIN_REGEX` — optional, tightly scoped preview URL regex

Generate a public Railway domain after the deployment passes its health check.

### Vercel frontend

Import the same GitHub repository into Vercel with:

- Root Directory: `frontend`
- Framework Preset: Next.js
- Production branch: `main`
- Environment variable: `NEXT_PUBLIC_API_URL=<Railway public backend URL>`

Vercel creates preview deployments for pull requests and production deployments
from `main`. Keep production and preview variables separate. Preview pages that
call the Railway API must have their origins explicitly allowed by the backend;
do not use an unrestricted wildcard origin.

## Safety

CareDelta is currently developed and demonstrated with synthetic data only. Do
not enter real patient information. AI-derived content must be redacted before
external model processing, treated as an untrusted candidate signal, and
reviewed before it can become patient-facing or trusted clinical memory.
