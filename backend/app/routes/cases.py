"""Case images (PNG) and CT/MR voxel volumes (gzipped int16), long cache. No case metadata is exposed here
(ground-truth invariant): the label volume is served only by /attempts/{aid}/maskvol after submit."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from backend.app.cases import get_repo

router = APIRouter(tags=["cases"])
LONG_CACHE = "public, max-age=31536000, immutable"
GZ_HEADERS = {"Cache-Control": LONG_CACHE, "Content-Encoding": "identity", "X-Content-Type-Options": "nosniff"}


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


@router.get("/cases/{case_id}/volume", response_class=Response)
def volume(case_id: str) -> Response:
    """The voxel volume as stored: gzip of int16 little-endian (z, y, x). Served with Content-Encoding: identity so the
    browser hands the gzip bytes to the client, which inflates them (DecompressionStream). Voxels only."""
    repo = get_repo()
    case = repo.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    p = repo.volume_path(case)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail="volume not found")
    return Response(p.read_bytes(), media_type="application/octet-stream", headers=GZ_HEADERS)
