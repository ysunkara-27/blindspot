"""Reference bank: card text plus outlined example films per label ("what does X look like").

Examples are bench-split cases only (evaluation-only, never served to learners), so the outlines are not a leak of
any case a learner can be shown. Behind the same access gate as the rest of /api when hosted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
