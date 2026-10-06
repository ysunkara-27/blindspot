"""Attempts: hint, submit (scoring + reveal or assessment receipt), stored result, debrief polling, ask the tutor."""

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


@router.get("/attempts/{aid}/result", response_model=services.AttemptResult)
def result(aid: str) -> services.AttemptResult:
    """The stored SubmitResult of a submitted attempt plus `case` {case_id, image_url, width, height} and
    `submitted` {marks, patterns, declared_normal, normal_confidence} (per-case review from the session summary).
    404 unknown, 409 before submit, 409 for an assessment attempt until that assessment is complete."""
    return services.get_result(aid)


@router.get("/attempts/{aid}/debrief", response_model=DebriefResponse, response_model_exclude_none=True)
def debrief(aid: str, background: BackgroundTasks) -> DebriefResponse:
    job = services.ensure_debrief(aid)  # assessment attempts: generated lazily once the session is complete
    if job is not None:
        background.add_task(services.run_debrief_job, **job)
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


@router.get("/attempts/{aid}/anatomy")
def anatomy(aid: str) -> dict:
    """Simplified zone outlines for 'Show anatomy'. 409 before submit (and in assessment until the summary)."""
    return services.anatomy(aid)
