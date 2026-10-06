"""Learner and cohort dashboards (SPEC §10). Real attempts only; every block reports n."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app import services
from backend.app.analytics.cohort import cohort_dashboard
from backend.app.analytics.learner import learner_dashboard
from backend.app.cases import get_repo
from backend.app.db import row, rows, tx

router = APIRouter(tags=["dashboard"])


@router.get("/learners/{lid}/dashboard")
def learner(
    lid: str, mode: str | None = Query(default=None, description="filter by mode; default excludes assessment")
) -> dict:
    with tx() as con:
        lr = row(con, "SELECT id, display_name, level FROM learners WHERE id=?", lid)
        if lr is None:
            raise HTTPException(status_code=404, detail="learner not found")
        q = "SELECT * FROM attempts WHERE learner_id=? AND submitted_at IS NOT NULL"
        args: list = [lid]
        if mode:
            q += " AND mode=?"
            args.append(mode)
        else:
            q += " AND mode NOT IN ('assess_A','assess_B')"
        atts = rows(con, q + " ORDER BY submitted_at", *args)
        ab = {
            r["label"]: (r["theta"], r["n"])
            for r in rows(con, "SELECT label, theta, n FROM ability WHERE learner_id=?", lid)
        }
    repo = get_repo()
    out = learner_dashboard([services.parse_attempt(a, repo) for a in atts], ab)
    out["learner"] = lr
    return out


@router.get("/cohort/dashboard")
def cohort(
    level: str | None = None,
    mode: str | None = None,
    date_from: str | None = Query(default=None, description="ISO date/time, inclusive"),
    date_to: str | None = Query(default=None, description="ISO date/time, exclusive"),
) -> dict:
    q = "SELECT a.* FROM attempts a JOIN learners l ON l.id = a.learner_id WHERE a.submitted_at IS NOT NULL"
    args: list = []
    if level:
        q += " AND l.level=?"
        args.append(level)
    if mode:
        q += " AND a.mode=?"
        args.append(mode)
    if date_from:
        q += " AND a.submitted_at>=?"
        args.append(date_from)
    if date_to:
        q += " AND a.submitted_at<?"
        args.append(date_to)
    with tx() as con:
        atts = rows(con, q + " ORDER BY a.submitted_at", *args)
        bvals = {r["case_id"]: r["b"] for r in rows(con, "SELECT case_id, b FROM case_difficulty")}
    repo = get_repo()
    out = cohort_dashboard([services.parse_attempt(a, repo) for a in atts], bvals)
    out["filters"] = {"level": level, "mode": mode, "date_from": date_from, "date_to": date_to}
    return out
