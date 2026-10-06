"""Attempts: hint, submit (scoring + reveal or assessment receipt), debrief polling, ask the tutor."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from backend.app import services
from backend.app.db import new_id, now_iso, tx
from shared.contracts import (
    AskRequest,
    AskResponse,
    AssessmentRecorded,
    AttemptSubmit,
    DebriefResponse,
    HintRequest,
    HintResponse,
    SubmitResult,
)

router = APIRouter(tags=["attempts"])


@router.post("/attempts/{aid}/hint", response_model=HintResponse)
def hint(aid: str, body: HintRequest) -> HintResponse:
    return services.hint(aid, body)


@router.post("/attempts/{aid}/submit", response_model=SubmitResult | AssessmentRecorded)
def submit(aid: str, body: AttemptSubmit, background: BackgroundTasks) -> SubmitResult | AssessmentRecorded:
    result, job = services.submit(aid, body)
    if job is not None:
        background.add_task(services.run_debrief_job, **job)
    return result


@router.get("/attempts/{aid}/debrief", response_model=DebriefResponse, response_model_exclude_none=True)
def debrief(aid: str) -> DebriefResponse:
    return services.get_debrief(aid)


@router.post("/attempts/{aid}/ask", response_model=AskResponse)
def ask(aid: str, body: AskRequest) -> AskResponse:
    return services.ask(aid, body.question)


class FlagRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/attempts/{aid}/flag")
def flag(aid: str, body: FlagRequest) -> dict:
    """'This seems wrong' on a debrief → goes to the /review queue."""
    with tx() as con:
        services._attempt(con, aid)
        con.execute(
            "INSERT INTO flags(id, attempt_id, comment, created_at) VALUES (?,?,?,?)",
            (new_id(), aid, body.comment, now_iso()),
        )
    return {"ok": True}
