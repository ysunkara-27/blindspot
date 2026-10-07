"""Reference bank: card text plus outlined example films per label ("what does X look like").

Examples are bench-split cases only (evaluation-only, never served to learners), so the outlines are not a leak of
any case a learner can be shown. Behind the same access gate as the rest of /api when hosted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.app import reference as bank

router = APIRouter(tags=["reference"])


@router.get("/reference", response_model=bank.ReferenceBank)
def reference() -> dict:
    return bank.reference()


@router.get("/reference/{label}", response_model=bank.ReferenceLabel)
def reference_label(label: str) -> dict:
    entry = bank.reference_label(label)
    if entry is None:
        raise HTTPException(status_code=404, detail="label not found")
    return entry


@router.get("/reference/{case_id}/maskvol", response_class=Response)
def reference_maskvol(case_id: str) -> Response:
    """Label volume (gzip uint8) of a BENCH CT/MR reference example. 404 for any case that could be served to a
    learner (practice / assessment splits) — bench cases never are, so this is not a ground-truth leak."""
    data = bank.reference_maskvol(case_id)
    if data is None:
        raise HTTPException(status_code=404, detail="not a reference case")
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "Content-Encoding": "identity", "X-Content-Type-Options": "nosniff"},
    )
