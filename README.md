# CareDelta

Source-backed clinical change radar for safer handoffs.

## Current implementation

The repository currently contains:

- `backend/`: FastAPI API with a `GET /health` endpoint
- `frontend/`: Next.js App Router application with TypeScript and Tailwind CSS
- Phase 2 domain models and a `MemoryRepository` populated with synthetic data
- A patient record page with a source-backed glance card and longitudinal timeline

### Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+

### Start the backend

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify the API in another terminal:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"caredelta-api"}
```

Fetch the complete synthetic patient record:

```bash
curl http://localhost:8000/api/patients/patient-syn-001/record
```

The response includes the patient, highlights with exact provenance pointers,
open tasks, timeline entries, comments, versions, audit logs, interaction
events, and conflicts. Phase 2 uses an in-process `MemoryRepository`; restarting
the backend resets it to the deterministic synthetic seed.

### Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The page requests the
complete synthetic patient record and displays its top/glance card, open actions,
conflict warning, comments, and longitudinal timeline. Click any glance-card
signal to scroll to and highlight its exact source text.

The frontend uses `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`) for
browser requests to the API.

### Run checks

```bash
cd backend
source .venv/bin/activate
pytest
```

```bash
cd frontend
npm run lint
npm run build
```
