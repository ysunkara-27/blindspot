"""FastAPI app. Routes live in backend/app/routes/ (backend-engineer); hosting glue in backend/app/hosting.py.

`create_app()` reads build-time settings (CORS origins, whether to serve frontend/dist). Base path and access-code
gates are read per request, so the module-level `app` follows env changes in tests.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.hosting import BasePathMiddleware, GateMiddleware, mount_frontend
from backend.app.settings import get_settings
from shared.contracts import Health

log = logging.getLogger("blindspot")
APP_VERSION = "0.1.0"
DEV_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
ROUTE_MODULES = ("access", "sessions", "attempts", "cases", "dashboard", "review", "pilot", "dev", "about", "reference")


def _case_count() -> int:
    try:
        from backend.app.cases import get_repo

        return get_repo().count()
    except Exception:  # noqa: BLE001 — health must answer even if the data is missing
        p = get_settings().processed_dir / "cases.jsonl"
        return sum(1 for _ in p.open()) if p.exists() else 0


def health() -> Health:
    s = get_settings()
    return Health(ok=True, offline=s.offline, cases=_case_count(), version=APP_VERSION)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create the SQLite schema once, before the first request (first-run safety; see backend/app/db.py)."""
    try:
        from backend.app.db import init_db

        init_db()
    except Exception:  # noqa: BLE001 — connect() retries lazily; startup must not die on a read-only volume
        log.exception("database initialisation at startup failed")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Blindspot API",
        version=APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    # add_middleware prepends: last added runs first. Order outer → inner: base path, CORS, gate/no-store.
    app.add_middleware(GateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys(DEV_ORIGINS + s.cors_origins)),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BasePathMiddleware)
    app.add_api_route("/api/health", health, methods=["GET"], response_model=Health)
    for mod in ROUTE_MODULES:
        try:
            m = importlib.import_module(f"backend.app.routes.{mod}")
            app.include_router(m.router, prefix="/api")
        except ModuleNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("failed to mount routes.%s", mod)
    if s.blindspot_serve_frontend:
        if (s.frontend_dist / "index.html").exists():
            mount_frontend(app, s.frontend_dist)
        else:
            log.warning("BLINDSPOT_SERVE_FRONTEND=1 but %s/index.html is missing; not serving the SPA", s.frontend_dist)
    return app


app = create_app()
