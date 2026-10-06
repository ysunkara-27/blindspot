"""Sessions: create, next case (never ground truth), summary."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app import services
from shared.contracts import AssessmentSummary, NextCase, SessionCreate, SessionCreated

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionCreated)
def create_session(body: SessionCreate) -> SessionCreated:
    return services.create_session(body)


@router.get("/sessions/{sid}/next", response_model=NextCase)
def next_case(sid: str) -> NextCase:
    return services.next_case(sid)


@router.get("/sessions/{sid}/summary", response_model=AssessmentSummary)
def summary(sid: str) -> AssessmentSummary:
    return services.summary(sid)
