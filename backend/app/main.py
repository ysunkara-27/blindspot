"""FastAPI app. Routes live in backend/app/routes/ (backend-engineer). This file is the M0 scaffold."""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.settings import get_settings
from shared.contracts import Health

log = logging.getLogger("blindspot")
APP_VERSION = "0.1.0"

app = FastAPI(title="Blindspot API", version=APP_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _case_count() -> int:
    try:
        from backend.app.cases import get_repo  # provided by backend-engineer (M3)

        return get_repo().count()
    except Exception:  # noqa: BLE001 — scaffold tolerance until M3 lands
        p = get_settings().processed_dir / "cases.jsonl"
        return sum(1 for _ in p.open()) if p.exists() else 0


@app.get("/api/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    return Health(ok=True, offline=s.offline, cases=_case_count(), version=APP_VERSION)


# Mount route modules if present (M3+). Each module exposes `router`.
for _mod in ("sessions", "attempts", "cases", "dashboard", "review", "dev", "about"):
    try:
        m = importlib.import_module(f"backend.app.routes.{_mod}")
        app.include_router(m.router, prefix="/api")
    except ModuleNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        log.exception("failed to mount routes.%s", _mod)
