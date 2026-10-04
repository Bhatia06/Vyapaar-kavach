# Run & Diagnostics — Vyapaar Kavach

Everything below is Windows PowerShell-accurate and tested on the submission machine. Start every command from `vyapaar-kavach/` unless stated otherwise.

## 1. Prerequisites

| Requirement | Check | Install hint |
|---|---|---|
| Python 3.11+ | `python --version` | python.org |
| Node 20+ (frontend only) | `node --version` | nodejs.org |
| Docker (optional, Postgres only) | `docker info` | Docker Desktop |
| torch + torch_geometric (ML runs only) | `python -c "import torch, torch_geometric"` | see requirements-ml.txt |

## 2. Environment variables

Copy `.env.example` → `.env` (optional; defaults work). All settings:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./vyapaar.db` | DB; Postgres string for compose path |
| `APP_ENVIRONMENT` | `DEMO_LOCAL` | only supported mode |
| `DEMO_OWNER_PASSWORD` / `DEMO_STAFF_PASSWORD` / `DEMO_RESEARCHER_PASSWORD` | owner123/staff123/research123 | seeded demo accounts |
| `ML_DATASET_PATH` | `../dataset1 (1).pt` | Elliptic2 subgraph dataset (parent dir) |
| `ML_CHECKPOINT_PATH` | `../GAT_Model_Final (2).pt` | trained checkpoint (parent dir) |
| `EXPORTS_DIR` | `services/api/artifacts/exports` | where evidence packets are written |
| `SESSION_SECURE` | `false` | set true only behind HTTPS |

## 3. Clean install & run

```powershell
pip install -r requirements.txt
python -m services.api.fixtures.seed          # creates tables + synthetic world
uvicorn services.api.app.main:app --port 8000 # http://127.0.0.1:8000/docs

# second terminal:
cd apps/web
npm install
npm run dev                                   # http://localhost:5173
```

Log in with `owner@demo/owner123`, `staff@demo/staff123`, or `research@demo/research123`.

**ML research runs** also need the dataset/checkpoint present at the paths above (they ship next to this folder by default) and `pip install -r requirements-ml.txt` if torch/torch_geometric are missing.

## 4. Verification

```powershell
python -m pytest services/api/tests -q        # expect: 13 passed
python -m ml.reproduce                        # expect: F1 0.5558, PR-AUC 0.5906
```

Health: `GET http://127.0.0.1:8000/health/live` → `{"status":"ok"}`; `/health/ready` includes DB check.

## 5. Demo runbook (5 minutes)

1. **F1 pending refund:** Home → search `ORD-3000-RAM` → New claim (prefilled) → REFUND_NOT_RECEIVED, ₹500 → recommendation: track existing refund `REF-500-001` (PENDING).
2. **F2 unknown outcome:** New claim → reference `ORD-1000-KIRAN` → `REFUND_OUTCOME_UNKNOWN`, missing `current_refund_outcome` — no second payout suggested.
3. **F3 ambiguity:** New claim → PAYMENT_NOT_REFLECTED, ₹799, no reference → two candidates → confirm one explicitly.
4. **Failure honesty:** Research page → Demo controls → `outage_on` → refresh payment → 503 + STALE. `delayed_pending_f1` → payment stays SUCCEEDED, verification CONFLICTED. `refund_f1_succeeds` → refund completes → recommendation flips to REFUND_SUCCEEDED.
5. **Research:** Research page → Run inference (sample 64) → real GATv2 metrics + artifact hashes; try task edit to see abstention.
6. **Evidence:** Case → Export → view Markdown, download JSON, note the SHA-256.

## 6. Diagnostics

| Symptom | Likely cause | Fix |
|---|---|---|
| `No module named services` | wrong working directory | run from `vyapaar-kavach/`, use `python -m services.api...` |
| `FATAL: port 8000 in use` | old uvicorn running | `Get-Process python` / stop it, or use `--port 8001` |
| `sqlite3.OperationalError: database is locked` | another process holds the db | close the other client; worst case stop all python and re-seed |
| npm blocked (`npm.ps1 ... running scripts`) | PowerShell execution policy | use `npm.cmd install` / `npm.cmd run dev` |
| Login 401 | wrong credentials world reset | passwords from `.env`; re-seed: `python -m services.api.fixtures.seed --reset` |
| `SESSION_EXPIRED` quickly | cookie not sent by client | browser: same-origin localhost; API: keep the `vk_session` cookie |
| Refresh returns 503 | outage toggle is ON (persisted in db) | demo controls → `outage_off`, or re-seed |
| Payments show STALE | seed timestamps aged past 15-min freshness | press Refresh on the payment, or re-seed |
| Research run abstains `MODEL_ARTIFACT_UNAVAILABLE` | .pt paths wrong | check `.env` paths vs actual files |
| Research run abstains `INFERENCE_ERROR` | torch/pyg missing or wrong versions | `pip install -r requirements-ml.txt` and retry |
| Research run is slow first time | dataset (~180 MB) + model load | cached after first run in a living process |
| Frontend blank / 401 loop | API down or wrong base URL | verify http://127.0.0.1:8000/health/live; set `VITE_API_BASE` |
| Exports 404 after move | files under `EXPORTS_DIR` moved | keep the folder; re-export |

## 7. Inspecting the database

```powershell
python -c "import sqlite3; con=sqlite3.connect('vyapaar.db'); [print(r) for r in con.execute('select order_ref from orders')]"
```

Export integrity check (verify a packet matches its recorded digest):

```powershell
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" services/api/artifacts/exports/exp_XXXX.md
```

Compare against the `sha256` returned by `POST /v1/cases/{id}/exports` (or the `exports` table).

## 8. Full reset

```powershell
# stop the API, then:
Remove-Item vyapaar.db -ErrorAction SilentlyContinue
Remove-Item vyapaar.db-wal, vyapaar.db-shm -ErrorAction SilentlyContinue
python -m services.api.fixtures.seed
```

Tests never touch `vyapaar.db` (they run against `.test_artifacts/test.db`).

## 9. Postgres (optional)

```powershell
docker compose up -d db
$env:DATABASE_URL="postgresql+psycopg2://vyapaar:vyapaar@localhost:5432/vyapaar"
python -m services.api.fixtures.seed --reset
uvicorn services.api.app.main:app --port 8000
```

Unset the variable (or remove `.env`) to return to SQLite.
