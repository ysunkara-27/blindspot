"""Sign schematics: generic line art of the classic signs (content/signs/<id>.yaml, SignSchematic contract).

Not case-specific and never ground truth of any case, so they sit behind no reveal gate (same access gate as the
rest of /api when hosted).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.signs import load_schematics
from shared.contracts import SignSchematic

router = APIRouter(tags=["signs"])


@router.get("/signs", response_model=list[SignSchematic])
def signs() -> list[SignSchematic]:
    return list(load_schematics().values())


@router.get("/signs/{sign_id}", response_model=SignSchematic)
def sign(sign_id: str) -> SignSchematic:
    s = load_schematics().get(sign_id)
    if s is None:
        raise HTTPException(status_code=404, detail="sign not found")
    return s
