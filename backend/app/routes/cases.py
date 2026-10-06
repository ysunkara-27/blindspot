"""Case images (PNG, long cache). No case metadata is exposed here (ground-truth invariant)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.app.cases import get_repo

router = APIRouter(tags=["cases"])
LONG_CACHE = "public, max-age=31536000, immutable"


@router.get("/cases/{case_id}/image", response_class=FileResponse)
def image(case_id: str) -> FileResponse:
    repo = get_repo()
    case = repo.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    p = repo.image_path(case)
    if not p.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": LONG_CACHE})
