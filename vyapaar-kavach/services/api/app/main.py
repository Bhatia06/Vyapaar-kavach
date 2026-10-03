"""FastAPI application entry point.

Run from the repo root:

    python -m services.api.fixtures.seed     # create schema + synthetic demo data
    uvicorn services.api.app.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import create_all
from .api.routes import auth, cases, exports, health, payments, provider_events, research

app = FastAPI(
    title="Vyapaar Kavach — merchant payment exception prototype",
    version="0.1.0",
    description=(
        "Synthetic demo mode only. All provider integration is mocked; no real "
        "funds move; ML output is restricted to original-domain research runs."
    ),
)

# Local development: allow the Vite dev server origin. Cookie auth is SameSite
# so this list is the only CORS exposure in the demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    create_all()


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(payments.router)
app.include_router(cases.router)
app.include_router(exports.router)
app.include_router(provider_events.router)
app.include_router(research.router)
