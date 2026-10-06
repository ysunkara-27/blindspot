"""Operator endpoints (review-gated by hosting.REVIEW_PREFIXES): tutor spend report and early resume of a pause."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.db import tx
from backend.app.tutor import spend
from backend.app.tutor.guard import get_guard, tutor_status

router = APIRouter(tags=["admin"])


@router.get("/admin/spend")
def admin_spend() -> dict[str, Any]:
    """Estimated spend by hour (24 h) and day (30 d), totals, debrief counts by source, budgets and the guard."""
    with tx() as con:
        rep = spend.report(con)
    rep["budget_usd"] = spend.Budgets.from_settings().as_dict()
    rep["tutor"] = tutor_status(include_spend=False)
    rep["guard"] = get_guard().snapshot()
    return rep


@router.post("/admin/tutor/resume")
def admin_tutor_resume() -> dict[str, Any]:
    """Clear a pause early (credits bought, key fixed, budget raised). Budget pauses return if spend is still over."""
    get_guard().resume()
    spend.reset_cache()
    return {"ok": True, "tutor": tutor_status(include_spend=True)}
