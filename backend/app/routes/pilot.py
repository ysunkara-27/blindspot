"""Pilot tooling: System Usability Scale (SUS)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from backend.app.db import now_iso, tx
from shared.contracts import SusResult, SusSubmit

router = APIRouter(tags=["pilot"])


def sus_score(answers: list[int]) -> float:
    """Standard SUS: odd items contribute (a − 1), even items (5 − a); sum × 2.5 → 0–100."""
    if len(answers) != 10 or any(a not in (1, 2, 3, 4, 5) for a in answers):
        raise ValueError("SUS needs 10 answers on a 1–5 scale")
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return total * 2.5


@router.post("/sus", response_model=SusResult)
def sus(body: SusSubmit) -> SusResult:
    try:
        score = sus_score(body.answers)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with tx() as con:
        con.execute(
            "INSERT INTO sus(learner_id, answers_json, score, created_at) VALUES (?,?,?,?)",
            (body.learner_id, json.dumps(body.answers), score, now_iso()),
        )
    return SusResult(score=score)
