"""Flatten app routes across FastAPI versions (≥0.14x wraps included routers lazily)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.routing import APIRoute


def iter_api_routes(app) -> Iterator[tuple[str, APIRoute]]:
    def walk(routes, prefix: str):
        for r in routes:
            if isinstance(r, APIRoute):
                yield prefix + r.path, r
            elif hasattr(r, "original_router"):
                ctx = getattr(r, "include_context", None)
                yield from walk(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            elif hasattr(r, "routes"):
                yield from walk(r.routes, prefix + getattr(r, "path", ""))

    yield from walk(app.routes, "")
