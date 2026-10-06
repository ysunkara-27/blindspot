"""Hosting glue (deploy/README.md): base path, access-code gates, API cache headers, built-frontend serving.

All of it is inert in local dev: with BLINDSPOT_BASE_PATH, BLINDSPOT_ACCESS_CODE and BLINDSPOT_REVIEW_CODE unset,
paths are unchanged, nothing is gated, and the SPA is only served when BLINDSPOT_SERVE_FRONTEND=1.

Settings are read per request (get_settings() is cached), so tests can flip them with env + cache_clear().
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette._utils import get_route_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.settings import get_settings

ACCESS_HEADER, ACCESS_COOKIE = "x-blindspot-access", "bs_access"
REVIEW_HEADER, REVIEW_COOKIE = "x-blindspot-review", "bs_review"
OPEN_API_PATHS = frozenset({"/api/health", "/api/about", "/api/access"})
REVIEW_PREFIXES = ("/api/review/", "/api/cohort/", "/api/admin/")
REVIEW_OPEN = frozenset({"/api/review/access"})
NO_STORE = b"no-store"
ASSET_CACHE = "public, max-age=31536000, immutable"


# ------------------------------------------------------------------ codes and tokens (pure)
def cookie_token(code: str, purpose: str) -> str:
    """Cookie value derived from the code (the cookie never carries the code itself)."""
    return hmac.new(code.encode(), f"blindspot:{purpose}".encode(), hashlib.sha256).hexdigest()


def code_matches(given: str | None, code: str) -> bool:
    return given is not None and hmac.compare_digest(given.strip().encode(), code.encode())


def granted(headers: dict[str, str], cookies: dict[str, str], code: str | None, header: str, cookie: str) -> bool:
    """True when no code is configured, or the header carries the code, or the cookie carries its token."""
    if not code:
        return True
    if code_matches(headers.get(header), code):
        return True
    c = cookies.get(cookie)
    return c is not None and hmac.compare_digest(c.encode(), cookie_token(code, cookie).encode())


def gate_error(path: str, method: str, headers: dict[str, str], cookies: dict[str, str]) -> str | None:
    """Pure gate decision for a route path (relative to the base path). None = allowed, else the error code."""
    if method == "OPTIONS" or not (path == "/api" or path.startswith("/api/")):
        return None
    if path in OPEN_API_PATHS:
        return None
    s = get_settings()
    if not granted(headers, cookies, s.access_code, ACCESS_HEADER, ACCESS_COOKIE):
        return "access_code_required"
    if path.startswith(REVIEW_PREFIXES) and path not in REVIEW_OPEN:
        if not granted(headers, cookies, s.review_code, REVIEW_HEADER, REVIEW_COOKIE):
            return "review_code_required"
    return None


def _cookies(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


# ------------------------------------------------------------------ ASGI middlewares
class BasePathMiddleware:
    """`{base}/api/...` and `{base}/...` are routed as `/api/...` and `/...` by setting root_path (Starlette strips
    it when matching). Unprefixed paths keep working, so a proxy may strip the prefix or not. `{base}` → `{base}/`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        base = get_settings().base_path if scope["type"] in ("http", "websocket") else ""
        if base:
            path: str = scope["path"]
            if path == base and scope["type"] == "http":
                qs = scope.get("query_string", b"").decode()
                await RedirectResponse(base + "/" + (f"?{qs}" if qs else ""), status_code=307)(scope, receive, send)
                return
            if path.startswith(base + "/") and not scope.get("root_path", "").endswith(base):
                scope = dict(scope, root_path=scope.get("root_path", "") + base)
        await self.app(scope, receive, send)


class GateMiddleware:
    """Access-code gates + `Cache-Control: no-store` on every /api response that did not set its own (images do)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = get_route_path(scope)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        err = gate_error(path, scope["method"], headers, _cookies(headers.get("cookie", "")))
        if err is not None:
            resp = JSONResponse({"error": err}, status_code=401, headers={"Cache-Control": "no-store"})
            await resp(scope, receive, send)
            return
        if not path.startswith("/api"):
            await self.app(scope, receive, send)
            return

        async def send_no_store(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                hs = list(msg.get("headers", []))
                if not any(k.lower() == b"cache-control" for k, _ in hs):
                    hs.append((b"cache-control", NO_STORE))
                msg = dict(msg, headers=hs)
            await send(msg)

        await self.app(scope, receive, send_no_store)


def cookie_secure(request: Request) -> bool:
    """Secure when served over https directly or via a proxy (Vercel → HF Space sends X-Forwarded-Proto), and
    always when hosted under a base path. Plain-http local dev (no base path) keeps it off so the cookie sticks."""
    fwd = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or fwd == "https" or bool(get_settings().base_path)


def set_gate_cookie(resp: JSONResponse, request: Request, code: str, cookie: str, max_age_s: int) -> None:
    """httpOnly, SameSite=Lax, Path=<base path>, no Domain (so it belongs to whichever host the browser sees,
    e.g. ysunkara.com behind the Vercel rewrite)."""
    resp.set_cookie(
        cookie,
        cookie_token(code, cookie),
        max_age=max_age_s,
        path=get_settings().base_path or "/",
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )


# ------------------------------------------------------------------ built frontend (SPA)
def resolve_static(dist: Path, rel: str) -> Path | None:
    """File under dist for a request path, or None (never escapes dist)."""
    rel = rel.lstrip("/")
    if not rel:
        return None
    try:
        p = (dist / rel).resolve()
    except (OSError, ValueError):
        return None
    root = dist.resolve()
    return p if p.is_file() and p.is_relative_to(root) else None


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """GET/HEAD catch-all, registered after the API routers: real files from dist, else index.html (SPA fallback).
    Unknown /api paths stay JSON 404s."""
    index = dist / "index.html"

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str):  # noqa: ANN202
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        f = resolve_static(dist, full_path)
        if f is not None and f.name != "index.html":
            cache = ASSET_CACHE if full_path.startswith("assets/") else "no-cache"
            return FileResponse(f, headers={"Cache-Control": cache})
        if not index.exists():
            return JSONResponse({"detail": "frontend not built"}, status_code=404)
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
