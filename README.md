# CareDelta

Source-backed clinical change radar for safer handoffs.

## Phase 1: Project skeleton

The repository currently contains:

- `backend/`: FastAPI API with a `GET /health` endpoint
- `frontend/`: Next.js App Router application with TypeScript and Tailwind CSS

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

### Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The page requests the
backend health endpoint and displays whether the API is connected.

The frontend uses `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`) for
browser requests to the API.

### Run Phase 1 checks

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
