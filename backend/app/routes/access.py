"""Access codes for hosting (deploy/README.md). One screen in the frontend posts the code; we set an httpOnly cookie.

- GET  /api/access          → which gates are configured and which this browser has passed (never 401).
- POST /api/access {code}   → validates BLINDSPOT_ACCESS_CODE, sets `bs_access`.
- POST /api/review/access {code} → validates BLINDSPOT_REVIEW_CODE, sets `bs_review` (needs the access gate first).
Failed attempts are rate limited per client IP.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.hosting import (
    ACCESS_COOKIE,
    ACCESS_HEADER,
    REVIEW_COOKIE,
    REVIEW_HEADER,
    code_matches,
    granted,
    set_gate_cookie,
)
from backend.app.settings import get_settings

router = APIRouter(tags=["access"])
COOKIE_MAX_AGE_S = 14 * 24 * 3600
MAX_FAILURES, FAILURE_WINDOW_S = 10, 300.0
_failures: dict[str, deque[float]] = defaultdict(deque)


class AccessCode(BaseModel):
    code: str = Field(min_length=1, max_length=200)


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _limited(ip: str, now: float) -> bool:
    q = _failures[ip]
    while q and now - q[0] > FAILURE_WINDOW_S:
        q.popleft()
    return len(q) >= MAX_FAILURES


def reset_failures() -> None:
    _failures.clear()


def _check(request: Request, body: AccessCode, code: str | None, cookie: str) -> JSONResponse:
    if not code:
        return JSONResponse({"ok": True, "required": False})
    ip, now = _client(request), time.monotonic()
    if _limited(ip, now):
        return JSONResponse({"error": "too_many_attempts"}, status_code=429, headers={"Retry-After": "300"})
    if not code_matches(body.code, code):
        _failures[ip].append(now)
        return JSONResponse({"error": "invalid_code"}, status_code=401)
    resp = JSONResponse({"ok": True, "required": True})
    set_gate_cookie(resp, request, code, cookie, COOKIE_MAX_AGE_S)
    return resp


@router.get("/access")
def access_status(request: Request) -> dict:
    s = get_settings()
    h, c = {k.lower(): v for k, v in request.headers.items()}, dict(request.cookies)
    return {
        "access_required": s.access_code is not None,
        "access_granted": granted(h, c, s.access_code, ACCESS_HEADER, ACCESS_COOKIE),
        "review_required": s.review_code is not None,
        "review_granted": granted(h, c, s.review_code, REVIEW_HEADER, REVIEW_COOKIE),
        "base_path": s.base_path,
    }


@router.post("/access")
def access(request: Request, body: AccessCode) -> JSONResponse:
    return _check(request, body, get_settings().access_code, ACCESS_COOKIE)


@router.post("/review/access")
def review_access(request: Request, body: AccessCode) -> JSONResponse:
    return _check(request, body, get_settings().review_code, REVIEW_COOKIE)
