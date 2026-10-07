"""Learner and cohort dashboards (SPEC §10). Real attempts only; every block reports n."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app import config, services
from backend.app.analytics.cohort import cohort_dashboard
from backend.app.analytics.learner import learner_dashboard, misses_by_zone
from backend.app.cases import get_repo
from backend.app.db import row, rows, tx

router = APIRouter(tags=["dashboard"])


@router.get("/learners/{lid}/dashboard")
def learner(
    lid: str,
    mode: str | None = Query(default=None, description="filter by mode; default excludes assessment"),
    modality: str | None = Query(default=None, description="cxr | ct | mr: every block over that modality only"),
) -> dict:
    """`modality` filters every block and is echoed back; `n_by_modality` always counts the unfiltered attempts; for
    ct/mr the volumetric `misses_by_zone` block is added (round-4 contract, docs/PROGRESS.md)."""
    if modality is not None and modality not in config.MODALITIES:
        raise HTTPException(status_code=422, detail=f"modality must be one of {', '.join(config.MODALITIES)}")
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
    recs = [services.parse_attempt(a, repo) for a in atts]
    n_by = {m: sum(r["modality"] == m for r in recs) for m in config.MODALITIES}
    if modality:
        recs = [r for r in recs if r["modality"] == modality]
    out = learner_dashboard(recs, ab)
    out["learner"] = lr
    out["modality"] = modality
    out["n_by_modality"] = n_by
    if modality in ("ct", "mr"):
        out["misses_by_zone"] = misses_by_zone(recs)
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
        levels = {r["id"]: r["level"] for r in rows(con, "SELECT id, level FROM learners")}
    repo = get_repo()
    out = cohort_dashboard([services.parse_attempt(a, repo) for a in atts], bvals, levels)
    out["filters"] = {"level": level, "mode": mode, "date_from": date_from, "date_to": date_to}
    return out
