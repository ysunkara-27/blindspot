"""Application services behind the routes: sessions, case selection, submit, debrief jobs, hints, ask, summary.

Ground-truth invariant: nothing derived from findings leaves this module before the attempt is submitted,
and assessment attempts never return feedback until the session summary.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from backend.app import config, tutor_bridge
from backend.app.adaptive.elo import apply_attempt
from backend.app.adaptive.selector import (
    CaseInfo,
    LearnerState,
    assessment_order,
    qa_ok,
    review_candidates,
    select_next,
)
from backend.app.cases import CaseRepository, get_repo
from backend.app.db import jload, new_id, now_iso, row, rows, tx
from backend.app.engine import Evaluation, evaluate
from backend.app.search.misstype import BUCKET
from backend.app.settings import get_settings
from shared.contracts import (
    AskResponse,
    AssessmentRecorded,
    AssessmentSummary,
    AttemptSubmit,
    Case,
    ClientTiming,
    DebriefFacts,
    DebriefResponse,
    HintRequest,
    HintResponse,
    Mark,
    NextCase,
    NextCaseCase,
    PatternSelection,
    SessionCreate,
    SessionCreated,
    SubmitResult,
)

log = logging.getLogger("blindspot.services")
ASSESS_MODES = ("assess_A", "assess_B")
MAX_ASKS = 3  # SPEC §8.9: up to 3 follow-up questions per case
MISS_BUCKETS = ("search", "recognition", "decision", "interpretation", "overcall")  # summary row order
FOUND_RESULTS = ("found", "mislabeled", "pattern_found")  # localized, as in the facts card
DEMO_NAME, DEMO_CODE = "demo", "DEMO"  # learner created by `make demo` (backend/app/demo_seed.py)
DEFAULT_MAX_MARKS = 50  # QA issue 7; overridable by config/scoring.yaml submit.max_marks
SELECTIONS = ("adaptive", "weak_areas", "random")  # SessionCreate.settings.selection
# SessionCreate.settings.case_count bounds; overridable by config/adaptive.yaml session.{case_count_min,case_count_max}
CASE_COUNT_MIN, CASE_COUNT_MAX = 3, 50
PREVALENCE_MIN, PREVALENCE_MAX = 0.3, 0.7  # SPEC §9.2: instructor-settable range


class SubmittedRead(BaseModel):
    """What the learner submitted (their own input, echoed back for the per-case review page)."""

    marks: list[Mark]
    patterns: list[PatternSelection]
    declared_normal: bool
    normal_confidence: int | None = None


class AttemptResult(SubmitResult):
    """GET /attempts/{aid}/result: the stored SubmitResult plus which film it was and what the learner did, so the
    per-case review page can be opened from an attempt id alone (frontend CONTRACT CHANGE REQUEST, round 3).
    A superset of SubmitResult: every SubmitResult field is present and unchanged."""

    case: NextCaseCase
    submitted: SubmittedRead


def is_assessment(mode: str) -> bool:
    return mode in ASSESS_MODES


def _404(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


# ------------------------------------------------------------------ sessions
def _case_count_bounds() -> tuple[int, int]:
    c = config.adaptive().get("session") or {}
    return int(c.get("case_count_min", CASE_COUNT_MIN)), int(c.get("case_count_max", CASE_COUNT_MAX))


def clean_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the session options the engine reads (round-3 contract); other keys pass through untouched.

    case_count: int within bounds (else 422) · selection: one of SELECTIONS (else 422) · prevalence_abnormal (or the
    legacy key `prevalence`): float clamped to 0.3–0.7, dropped if not a number. `level` is not an engine input."""
    st = dict(raw or {})
    errs: list[str] = []
    cc = st.get("case_count")
    if cc is None:
        st.pop("case_count", None)
    else:
        lo, hi = _case_count_bounds()
        if isinstance(cc, float) and cc.is_integer():
            cc = int(cc)
        if isinstance(cc, bool) or not isinstance(cc, int) or not lo <= cc <= hi:
            errs.append(f"settings.case_count must be an integer from {lo} to {hi}")
        else:
            st["case_count"] = cc
    sel = st.get("selection")
    if sel is None:
        st.pop("selection", None)
    elif sel not in SELECTIONS:
        errs.append(f"settings.selection must be one of {', '.join(SELECTIONS)}")
    prev = st.pop("prevalence_abnormal", None)
    legacy = st.pop("prevalence", None)
    prev = legacy if prev is None else prev
    try:
        prev = None if prev is None or isinstance(prev, bool) else float(prev)
    except (TypeError, ValueError):
        prev = None
    if prev is not None and math.isfinite(prev):
        st["prevalence_abnormal"] = min(PREVALENCE_MAX, max(PREVALENCE_MIN, prev))
    if errs:
        raise HTTPException(status_code=422, detail=errs)
    return st


def create_session(body: SessionCreate) -> SessionCreated:
    now = now_iso()
    settings = clean_settings(body.settings)
    with tx(immediate=True) as con:
        lid = None
        want = body.settings.get("learner_id") if body.settings else None
        if want and row(con, "SELECT id FROM learners WHERE id=?", want):
            lid = want
        elif body.participant_code:
            r = row(
                con,
                "SELECT id FROM learners WHERE participant_code=? ORDER BY created_at LIMIT 1",
                body.participant_code,
            )
            lid = r["id"] if r else None
        if lid is None and not body.participant_code and body.display_name.strip().casefold() == DEMO_NAME:
            r = row(con, "SELECT id FROM learners WHERE participant_code=? ORDER BY created_at LIMIT 1", DEMO_CODE)
            lid = r["id"] if r else None
        if lid is not None and body.mode == "practice" and "playlist" not in settings:
            settings.update(_demo_playlist_settings(con, lid))
        if lid is None:
            lid = new_id()
            con.execute(
                "INSERT INTO learners(id, display_name, level, participant_code, created_at) VALUES (?,?,?,?,?)",
                (lid, body.display_name, body.level, body.participant_code, now),
            )
        sid = new_id()
        con.execute(
            "INSERT INTO sessions(id, learner_id, mode, settings_json, started_at) VALUES (?,?,?,?,?)",
            (sid, lid, body.mode, json.dumps(settings), now),
        )
    return SessionCreated(session_id=sid, learner_id=lid, mode=body.mode)


def _demo_playlist_settings(con, lid: str) -> dict[str, Any]:
    """The seeded demo learner (participant_code DEMO, see demo_seed.py) gets the seeded playlist on every new
    Practice session, so typing "Demo" on the onboarding page replays the playlist from slot 1."""
    lr = row(con, "SELECT participant_code FROM learners WHERE id=?", lid)
    if not lr or lr["participant_code"] != DEMO_CODE:
        return {}
    for r in rows(con, "SELECT settings_json FROM sessions WHERE learner_id=? ORDER BY started_at DESC", lid):
        pl = jload(r["settings_json"], {}).get("playlist")
        if isinstance(pl, list) and pl:
            return {"playlist": pl}
    return {}


def _session(con, sid: str) -> dict[str, Any]:
    s = row(con, "SELECT * FROM sessions WHERE id=?", sid)
    if s is None:
        raise _404("session")
    s["settings"] = jload(s["settings_json"], {})
    return s


def _servable(repo: CaseRepository, cid: str) -> bool:
    """Case exists and carries no QA flag outside the allowlist (selector.BENIGN_FLAGS)."""
    c = repo.get(cid)
    if c is None:
        return False
    if not qa_ok(c.qa_flags):
        log.warning("refusing to serve %s: qa_flags=%s", cid, c.qa_flags)
        return False
    return True


def _assessment_ids(repo: CaseRepository, mode: str) -> list[str]:
    """Fixed order: data/processed/splits.json[mode] if it is an ordered list, else seeded order of the split.
    QA-flagged cases (outside the allowlist) are dropped with a warning (REVIEW_NOTES issue 11)."""
    p = repo.root / "splits.json"
    if p.exists():
        try:
            d = json.loads(p.read_text())
            ids = d.get(mode)
            if isinstance(ids, list) and ids and all(isinstance(x, str) for x in ids):
                return [i for i in ids if _servable(repo, i)]
        except (ValueError, AttributeError):
            pass
    return assessment_order([c.case_id for c in repo.by_split(mode) if _servable(repo, c.case_id)])


def _b_values(con) -> dict[str, tuple[float, int]]:
    return {r["case_id"]: (r["b"], r["n"]) for r in rows(con, "SELECT case_id, b, n FROM case_difficulty")}


def _abilities(con, lid: str) -> dict[str, tuple[float, int]]:
    return {
        r["label"]: (r["theta"], r["n"])
        for r in rows(con, "SELECT label, theta, n FROM ability WHERE learner_id=?", lid)
    }


def _case_info(c: Case, bvals: dict[str, tuple[float, int]]) -> CaseInfo:
    b = bvals.get(c.case_id, (c.difficulty_prior, 0))[0]
    return CaseInfo(
        c.case_id, c.is_normal, tuple(dict.fromkeys(f.label for f in c.findings)), b, c.split, tuple(c.qa_flags)
    )


def image_url(case_id: str) -> str:
    """Public image URL; carries the base path when hosted under one (BLINDSPOT_BASE_PATH)."""
    return f"{get_settings().api_prefix}/cases/{case_id}/image"


def _next_case_payload(aid: str, case: Case, index: int, total: int | None, hints_enabled: bool) -> NextCase:
    return NextCase(
        attempt_id=aid,
        case=NextCaseCase(
            case_id=case.case_id, image_url=image_url(case.case_id), width=case.width, height=case.height
        ),
        index=index,
        total=total,
        hints_enabled=hints_enabled,
    )


def _done(index: int, total: int | None) -> NextCase:
    return NextCase(
        attempt_id="",
        case=NextCaseCase(case_id="", image_url="", width=0, height=0),
        index=index,
        total=total,
        hints_enabled=False,
        done=True,
    )


def _playlist_ids(repo: CaseRepository, settings: dict) -> list[str]:
    """Servable practice-split cases of settings.playlist, in order, de-duplicated (missing/flagged/other-split
    entries are skipped)."""
    pl = settings.get("playlist")
    if not isinstance(pl, list):
        return []
    out: list[str] = []
    for cid in pl:
        if not isinstance(cid, str) or cid in out or not _servable(repo, cid):
            continue
        c = repo.get(cid)
        if c is not None and c.split == "practice":
            out.append(cid)
    return out


def session_total(repo: CaseRepository, s: dict[str, Any]) -> int | None:
    """Planned number of cases: the assessment form length; else the playlist length (Demo learner; wins over
    case_count); else settings.case_count; else None (open-ended)."""
    if is_assessment(s["mode"]):
        return len(_assessment_ids(repo, s["mode"]))
    st = s.get("settings") or {}
    pl = _playlist_ids(repo, st)
    if pl:
        return len(pl)
    cc = st.get("case_count")
    return int(cc) if isinstance(cc, int) and not isinstance(cc, bool) and cc > 0 else None


def _n_submitted(con, sid: str) -> int:
    return row(con, "SELECT COUNT(*) AS n FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL", sid)["n"]


def _end_session(con, sid: str) -> None:
    con.execute("UPDATE sessions SET ended_at=COALESCE(ended_at, ?) WHERE id=?", (now_iso(), sid))


def next_case(sid: str) -> NextCase:
    repo = get_repo()
    with tx(immediate=True) as con:  # read-then-insert: one writer at a time, so two /next calls share one attempt
        s = _session(con, sid)
        mode = s["mode"]
        assess = is_assessment(mode)
        total = session_total(repo, s)
        open_a = row(
            con, "SELECT * FROM attempts WHERE session_id=? AND submitted_at IS NULL ORDER BY idx DESC LIMIT 1", sid
        )
        if open_a:
            c = repo.get(open_a["case_id"])
            if c is not None:
                return _next_case_payload(open_a["id"], c, open_a["idx"] + 1, total, not assess)
        n_done = row(con, "SELECT COUNT(*) AS n FROM attempts WHERE session_id=?", sid)["n"]
        if total is not None and _n_submitted(con, sid) >= total:  # planned length reached: no new attempt
            _end_session(con, sid)
            return _done(n_done, total)
        if assess:
            ids = _assessment_ids(repo, mode)
            if n_done >= len(ids):
                _end_session(con, sid)
                return _done(n_done, total)
            case = repo.get(ids[n_done])
        else:
            case = _select_practice(con, repo, s, n_done)
            if case is None:
                return _done(n_done, total)
        aid = new_id()
        con.execute(
            "INSERT INTO attempts(id, session_id, learner_id, case_id, mode, idx, shown_at) VALUES (?,?,?,?,?,?,?)",
            (aid, sid, s["learner_id"], case.case_id, mode, n_done, now_iso()),
        )
    return _next_case_payload(aid, case, n_done + 1, total, not assess)


def _select_practice(con, repo: CaseRepository, s: dict, n_done: int) -> Case | None:
    sel = config.adaptive()["selection"]
    core = list(config.core_labels())
    lid, sid, mode, st = s["learner_id"], s["id"], s["mode"], s["settings"]
    bvals = _b_values(con)
    pool = [_case_info(c, bvals) for c in repo.all()]
    sess = rows(con, "SELECT case_id FROM attempts WHERE session_id=? ORDER BY idx", sid)
    recent = rows(
        con,
        "SELECT case_id FROM attempts WHERE learner_id=? ORDER BY shown_at DESC LIMIT ?",
        lid,
        int(sel["recent_window"]),
    )
    state = LearnerState(
        abilities=_abilities(con, lid),
        seen_in_session={r["case_id"] for r in sess},
        recent=[r["case_id"] for r in reversed(recent)],
    )
    infos = {c.case_id: c for c in pool}
    for r in sess:
        ci = infos.get(r["case_id"])
        if ci:
            state.n_drawn += 1
            state.n_abnormal_drawn += 0 if ci.is_normal else 1
    if sess and (last := infos.get(sess[-1]["case_id"])) and not last.is_normal:
        labs = [lab for lab in last.labels if lab in core] or list(last.labels)
        state.last_label = labs[0] if labs else None
    seed = int(hashlib.sha256(f"{sid}:{n_done}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)

    playlist = _playlist_pick(repo, st, sess)
    if playlist is not None:
        return playlist
    if mode == "review":
        cid = _review_pick(con, lid, state, rng)
        if cid and _servable(repo, cid) and (c := repo.get(cid)):
            return c
    prevalence = st.get("prevalence_abnormal", st.get("prevalence"))  # clean_settings clamps; old rows may not be
    try:
        prevalence = None if prevalence is None else min(PREVALENCE_MAX, max(PREVALENCE_MIN, float(prevalence)))
    except (TypeError, ValueError):
        prevalence = None
    drill = st.get("label") if mode == "drill" else None
    if drill is not None and drill not in config.labels():
        drill = None
    strategy = st.get("selection") if st.get("selection") in SELECTIONS else "adaptive"
    pick = select_next(
        pool,
        state,
        sel,
        rng,
        core=core,
        theta_init=config.adaptive()["elo"]["theta_init"],
        drill_label=drill,
        prevalence=prevalence,
        strategy=strategy,
    )
    return repo.get(pick.case_id) if pick else None


def _playlist_pick(repo: CaseRepository, settings: dict, sess: list[dict]) -> Case | None:
    """Session settings {"playlist": [case_id, ...]} (demo): serve those cases IN ORDER, skipping ones already
    shown in this session and any that are missing, QA-flagged or not in the practice split. The session's total is
    the playlist length (session_total), so /next reports done once every playlist case is submitted."""
    shown = {r["case_id"] for r in sess}
    for cid in _playlist_ids(repo, settings):
        if cid not in shown:
            return repo.get(cid)
    return None


def _review_pick(con, lid: str, state: LearnerState, rng: random.Random) -> str | None:
    hist = rows(
        con,
        "SELECT case_id, success, submitted_at FROM attempts WHERE learner_id=? AND submitted_at IS NOT "
        "NULL AND mode NOT IN ('assess_A','assess_B') ORDER BY submitted_at",
        lid,
    )
    last: dict[str, tuple[int, float, bool]] = {}
    for i, h in enumerate(hist):
        try:
            ts = time.mktime(time.strptime(h["submitted_at"][:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            ts = 0.0
        last[h["case_id"]] = (i, ts, bool(h["success"]))
    misses = [(cid, i, ts) for cid, (i, ts, ok) in last.items() if not ok and cid not in state.seen_in_session]
    gap = int(config.adaptive()["review_mode"]["min_gap_cases"])
    cands = review_candidates(misses, len(hist), time.time(), gap)
    return rng.choice(cands) if cands else None


# ------------------------------------------------------------------ attempts
def _attempt(con, aid: str) -> dict[str, Any]:
    a = row(con, "SELECT * FROM attempts WHERE id=?", aid)
    if a is None:
        raise _404("attempt")
    return a


def history_for(con, lid: str, labels: list[str], exclude_aid: str) -> dict[str, Any]:
    """Prior per-label attempts/localized counts and recent miss-type counts (last 10 attempts)."""
    hist = rows(
        con,
        "SELECT a.id, a.case_id, a.outcomes_json FROM attempts a WHERE a.learner_id=? AND a.id<>? AND "
        "a.submitted_at IS NOT NULL ORDER BY a.submitted_at",
        lid,
        exclude_aid,
    )
    repo = get_repo()
    out: dict[str, Any] = {lab: {"attempts": 0, "localized": 0} for lab in labels}
    recent = {"search": 0, "recognition": 0, "decision": 0}
    for i, h in enumerate(hist):
        c = repo.get(h["case_id"])
        outs = jload(h["outcomes_json"], [])
        if c is None:
            continue
        res = {o["target"]: o["result"] for o in outs}
        for f in c.findings:
            if f.label in out:
                out[f.label]["attempts"] += 1
                out[f.label]["localized"] += res.get(f.short_id) in ("found", "mislabeled", "pattern_found")
        if i >= len(hist) - 10:
            for o in outs:
                b = BUCKET.get(o["result"])
                if b in recent:
                    recent[b] += 1
    out["recent_miss_types"] = recent
    return out


def submit_problems(body: AttemptSubmit, width: float, height: float, max_marks: int) -> list[str]:
    """Pure check of a submit against the image (REVIEW_NOTES issue 7). Empty list = valid."""
    errs: list[str] = []
    if len(body.marks) > max_marks:
        errs.append(f"too many marks ({len(body.marks)} > {max_marks})")
    seen: set[str] = set()
    for m in body.marks:
        if m.mark_id in seen:
            errs.append(f"duplicate mark_id {m.mark_id!r}")
        seen.add(m.mark_id)
        if not (math.isfinite(m.x) and math.isfinite(m.y)):
            errs.append(f"mark {m.mark_id!r} has non-finite coordinates")
        elif not (0.0 <= m.x <= width and 0.0 <= m.y <= height):
            errs.append(f"mark {m.mark_id!r} is outside the image ({m.x:g}, {m.y:g}) not in [0,{width}]x[0,{height}]")
    for i, e in enumerate(body.telemetry):
        vals = [e.t, e.zoom, e.x, e.y, *(e.vp or ())]
        if any(v is not None and not math.isfinite(v) for v in vals):
            errs.append(f"telemetry event {i} has non-finite values")
            break
    if body.normal_confidence is not None and not math.isfinite(float(body.normal_confidence)):
        errs.append("normal_confidence is not finite")
    return errs


def validate_submit(body: AttemptSubmit, case: Case) -> None:
    max_marks = int(config.scoring().get("submit", {}).get("max_marks", DEFAULT_MAX_MARKS))
    errs = submit_problems(body, case.width, case.height, max_marks)
    if errs:
        raise HTTPException(status_code=422, detail=errs)


def submit(aid: str, body: AttemptSubmit) -> tuple[SubmitResult | AssessmentRecorded, dict | None]:
    """Returns (response, debrief_job_kwargs or None)."""
    repo = get_repo()
    with tx() as con:  # cheap pre-checks; the scoring below runs outside any write lock
        a = _attempt(con, aid)
    if a["submitted_at"]:
        raise HTTPException(status_code=409, detail="attempt already submitted")
    case = repo.get(a["case_id"])
    if case is None:
        raise _404("case")
    validate_submit(body, case)
    ev = evaluate(case, body, repo, hints_used=a["hints_used"])
    result = SubmitResult(
        score=ev.score,
        success=ev.success,
        outcomes=ev.outcomes,
        reveal=ev.reveal,
        facts_card=ev.facts_card,
        debrief_status="pending",
    )
    with tx(immediate=True) as con:
        a = _attempt(con, aid)
        if a["submitted_at"]:  # lost a double-submit race
            raise HTTPException(status_code=409, detail="attempt already submitted")
        hints = max(body.hints_used, a["hints_used"])
        assess = is_assessment(a["mode"])
        elo_log = None
        if not assess:
            elo_log = _update_elo(con, a["learner_id"], case, ev)
        con.execute(
            "UPDATE attempts SET submitted_at=?, declared_normal=?, normal_confidence=?, marks_json=?, patterns_json=?,"
            " hints_used=?, score=?, success=?, outcomes_json=?, search_json=?, elo_json=?, result_json=? WHERE id=?",
            (
                now_iso(),
                int(body.declared_normal),
                body.normal_confidence,
                json.dumps([m.model_dump() for m in body.marks]),
                json.dumps([p.model_dump() for p in body.patterns]),
                hints,
                ev.score,
                int(ev.success),
                json.dumps([o.model_dump(exclude_none=True) for o in ev.outcomes]),
                json.dumps(ev.search_json),
                json.dumps(elo_log) if elo_log else None,
                result.model_dump_json(),  # served again by GET /attempts/{id}/result (never before the reveal rules)
                aid,
            ),
        )
        con.execute(
            "INSERT OR REPLACE INTO telemetry(attempt_id, events_json, n_events) VALUES (?,?,?)",
            (aid, json.dumps([e.model_dump() for e in body.telemetry]), len(body.telemetry)),
        )
        sess = _session(con, a["session_id"])
        total = session_total(repo, sess)
        if total is not None and _n_submitted(con, a["session_id"]) >= total:
            _end_session(con, a["session_id"])
        if assess:
            return AssessmentRecorded(index=a["idx"] + 1, total=total), None
        job = _debrief_job(con, a, case, body, ev, sess)
    return result, job


def _debrief_job(con, a: dict, case: Case, body: AttemptSubmit, ev: Evaluation, sess: dict) -> dict[str, Any]:
    """Insert the pending debriefs row and return the kwargs for run_debrief_job."""
    aid = a["id"]
    learner = row(con, "SELECT level FROM learners WHERE id=?", a["learner_id"]) or {}
    history = history_for(con, a["learner_id"], sorted({f.label for f in case.findings}), aid)
    con.execute(
        "INSERT INTO debriefs(id, attempt_id, created_at, status) VALUES (?,?,?, 'pending')",
        (new_id(), aid, now_iso()),
    )
    focus = (sess.get("settings") or {}).get("label") if a["mode"] == "drill" else None
    return {
        "aid": aid,
        "case": case,
        "submit": body,
        "ev": ev,
        "level": learner.get("level") or "other",
        "history": history,
        "focus_label": focus if focus in config.labels() else None,
    }


def assessment_locked(con, repo: CaseRepository, a: dict) -> bool:
    """True for an assessment attempt whose session is not complete yet: nothing about it may be revealed."""
    if not is_assessment(a["mode"]):
        return False
    return _n_submitted(con, a["session_id"]) < len(_assessment_ids(repo, a["mode"]))


def stored_submit(a: dict, events: list[dict] | None) -> AttemptSubmit:
    """Rebuild the AttemptSubmit of a submitted attempt from its row (client timing ≈ server shown/submitted times)."""
    return AttemptSubmit.model_validate(
        {
            "marks": jload(a["marks_json"], []),
            "patterns": jload(a["patterns_json"], []),
            "declared_normal": bool(a["declared_normal"]),
            "normal_confidence": a["normal_confidence"],
            "telemetry": events or [],
            "hints_used": min(3, max(0, int(a["hints_used"] or 0))),
            "client_timing": ClientTiming(shown_at=a["shown_at"], submitted_at=a["submitted_at"]).model_dump(),
        }
    )


def _reevaluate(con, repo: CaseRepository, a: dict) -> tuple[Case, AttemptSubmit, Evaluation]:
    case = repo.get(a["case_id"])
    if case is None:
        raise _404("case")
    t = row(con, "SELECT events_json FROM telemetry WHERE attempt_id=?", a["id"])
    body = stored_submit(a, jload(t["events_json"], []) if t else [])
    return case, body, evaluate(case, body, repo, hints_used=a["hints_used"])


def get_result(aid: str) -> AttemptResult:
    """The SubmitResult of a submitted attempt (per-case review) plus `case` (film) and `submitted` (the learner's
    own marks and selections). 404 unknown · 409 not submitted · 409 for an assessment attempt until that
    assessment session is complete (ground-truth invariant)."""
    repo = get_repo()
    with tx() as con:
        a = _attempt(con, aid)
        if not a["submitted_at"]:
            raise HTTPException(status_code=409, detail="attempt not submitted")
        if assessment_locked(con, repo, a):
            raise HTTPException(status_code=409, detail="available after the assessment summary")
        case = repo.get(a["case_id"])
        if case is None:
            raise _404("case")
        if a.get("result_json"):
            res = SubmitResult.model_validate_json(a["result_json"])
        else:  # submitted before results were stored (e.g. the seeded demo history): scoring is deterministic
            _, _, ev = _reevaluate(con, repo, a)
            res = SubmitResult(
                score=ev.score,
                success=ev.success,
                outcomes=ev.outcomes,
                reveal=ev.reveal,
                facts_card=ev.facts_card,
                debrief_status="pending",
            )
    body = stored_submit(a, None)
    return AttemptResult(
        **{**res.model_dump(), "debrief_status": "pending"},
        case=NextCaseCase(
            case_id=case.case_id, image_url=image_url(case.case_id), width=case.width, height=case.height
        ),
        submitted=SubmittedRead(
            marks=body.marks,
            patterns=body.patterns,
            declared_normal=body.declared_normal,
            normal_confidence=body.normal_confidence,
        ),
    )


def ensure_debrief(aid: str) -> dict | None:
    """Lazy debrief for an assessment attempt (no debrief is generated while the assessment runs): on the first
    request after the session is complete, insert the pending row and return the run_debrief_job kwargs. None when
    nothing has to start (unknown/unsubmitted/locked attempt, or a debrief row already exists)."""
    repo = get_repo()
    with tx(immediate=True) as con:
        a = row(con, "SELECT * FROM attempts WHERE id=?", aid)
        if a is None or not a["submitted_at"] or not is_assessment(a["mode"]) or assessment_locked(con, repo, a):
            return None
        if row(con, "SELECT id FROM debriefs WHERE attempt_id=? LIMIT 1", aid):
            return None
        if repo.get(a["case_id"]) is None:
            return None
        case, body, ev = _reevaluate(con, repo, a)
        return _debrief_job(con, a, case, body, ev, _session(con, a["session_id"]))


def _update_elo(con, lid: str, case: Case, ev: Evaluation) -> dict:
    cfg = config.adaptive()["elo"]
    ab = _abilities(con, lid)
    bv = row(con, "SELECT b, n FROM case_difficulty WHERE case_id=?", case.case_id)
    b, n_case = (bv["b"], bv["n"]) if bv else (case.difficulty_prior, 0)
    new_ab, new_b, log_ = apply_attempt(ab, b, n_case, case.is_normal, ev.finding_results, ev.success, cfg)
    for lab, (th, n) in new_ab.items():
        if ab.get(lab) != (th, n):
            con.execute(
                "INSERT OR REPLACE INTO ability(learner_id, label, theta, n) VALUES (?,?,?,?)", (lid, lab, th, n)
            )
    con.execute(
        "INSERT OR REPLACE INTO case_difficulty(case_id, b, n) VALUES (?,?,?)", (case.case_id, new_b, n_case + 1)
    )
    return log_


# ------------------------------------------------------------------ debrief job (FastAPI BackgroundTask)
def _cache_get(key: str) -> dict | None:
    with tx() as con:
        return row(
            con,
            "SELECT output_json, source, model, prompt_version, validator_json FROM debriefs WHERE cache_key=? AND "
            "status='ready' AND output_json IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            key,
        )


def run_debrief_job(
    aid: str,
    case: Case,
    submit: AttemptSubmit,
    ev: Evaluation,
    level: str,
    history: dict,
    focus_label: str | None = None,
) -> None:
    t0 = time.perf_counter()
    try:
        facts = tutor_bridge.build_facts(
            case=case,
            submit=submit,
            outcomes=ev.outcomes,
            spatial_relations=ev.spatial_relations,
            search=ev.facts_search,
            mark_zones=ev.mark_zones,
            level=level,
            history=history,
        )
        if facts is None:
            _finish(aid, status="failed", error="The tutor is offline. Showing the built-in facts card instead.")
            return
        facts_json = facts.model_dump_json(by_alias=True)
        _finish(aid, status="pending", facts_json=facts_json)
        out = tutor_bridge.generate_debrief(
            facts,
            case,
            attempt_id=aid,
            submit=submit,
            offline=get_settings().offline,
            cache_get=_cache_get,
            focus_label=focus_label,
        )
        if out is None:
            _finish(aid, status="failed", error="The tutor is offline. Showing the built-in facts card instead.")
            return
        _finish(
            aid,
            status="ready",
            facts_json=facts_json,
            output_json=out["debrief"].model_dump_json(),
            cache_key=out.get("cache_key"),
            model=out.get("model"),
            prompt_version=out.get("prompt_version"),
            validator_json=json.dumps(out.get("validator") or {}),
            source=out.get("source", "template"),
            latency_ms=out.get("latency_ms", (time.perf_counter() - t0) * 1000),
            input_tokens=out.get("input_tokens"),
            output_tokens=out.get("output_tokens"),
            cache_read_tokens=out.get("cache_read_tokens"),
            provenance=out.get("provenance"),
            error=out.get("error"),
        )
    except Exception as e:  # noqa: BLE001 — a debrief failure must never break the read loop
        log.exception("debrief job failed for %s", aid)
        _finish(aid, status="failed", error=type(e).__name__)


def _finish(aid: str, **fields: Any) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with tx() as con:
        con.execute(f"UPDATE debriefs SET {cols} WHERE attempt_id=?", (*fields.values(), aid))


def get_debrief(aid: str) -> DebriefResponse:
    """Assessment attempts: "disabled" until the session is complete; afterwards like any other attempt (the route
    starts the lazy generation via ensure_debrief before calling this)."""
    repo = get_repo()
    with tx() as con:
        a = _attempt(con, aid)
        if assessment_locked(con, repo, a):
            return DebriefResponse(status="disabled")
        if not a["submitted_at"]:
            raise HTTPException(status_code=409, detail="attempt not submitted")
        d = row(con, "SELECT * FROM debriefs WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1", aid)
    if d is None or d["status"] == "pending":
        return DebriefResponse(status="pending")
    if d["status"] == "failed":
        return DebriefResponse(status="failed", error=d["error"])
    return DebriefResponse(
        status="ready",
        debrief=jload(d["output_json"]),
        source=d["source"],
        provenance=d["provenance"],
        validator=jload(d["validator_json"]),
        latency_ms=d["latency_ms"],
        error=d.get("error"),
    )


# ------------------------------------------------------------------ hints + ask
def hint(aid: str, body: HintRequest) -> HintResponse:
    max_h = int(config.scoring()["hints"]["max_per_case"])
    repo = get_repo()
    with tx() as con:
        a = _attempt(con, aid)
        if is_assessment(a["mode"]):
            raise HTTPException(status_code=403, detail="hints are disabled in assessment mode")
        if a["submitted_at"]:
            raise HTTPException(status_code=409, detail="attempt already submitted")
        if a["hints_used"] >= max_h:
            raise HTTPException(status_code=409, detail="no hints left")
        case = repo.get(a["case_id"])
        zones, _ = repo.zones(case.case_id)
        level = a["hints_used"] + 1
        prev = jload(a["hint_log_json"], [])
        text = tutor_bridge.hint(level, case, body.marks, body.telemetry, zones, previous=prev)
        log_ = prev + [{"level": level, "at": now_iso(), "text": text}]
        con.execute("UPDATE attempts SET hints_used=?, hint_log_json=? WHERE id=?", (level, json.dumps(log_), aid))
    return HintResponse(level=level, text=text, remaining=max_h - level)


def ask(aid: str, question: str) -> AskResponse:
    repo = get_repo()
    with tx() as con:
        a = _attempt(con, aid)
        if assessment_locked(con, repo, a):
            raise HTTPException(status_code=403, detail="the tutor is disabled until the assessment is complete")
        if not a["submitted_at"]:
            raise HTTPException(status_code=409, detail="submit the read first")
        prev = rows(con, "SELECT question, answer FROM asks WHERE attempt_id=? ORDER BY created_at", aid)
        if len(prev) >= MAX_ASKS:
            raise HTTPException(status_code=409, detail="no questions left for this case")
        d = row(con, "SELECT facts_json FROM debriefs WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1", aid)
    facts = DebriefFacts.model_validate_json(d["facts_json"]) if d and d.get("facts_json") else None
    case = repo.get(a["case_id"])
    out = tutor_bridge.ask(question, facts, case, previous=prev, offline=get_settings().offline)
    src = out.get("source") if out.get("source") in ("live", "template") else "template"
    with tx() as con:
        con.execute(
            "INSERT INTO asks(id, attempt_id, question, answer, created_at, source, input_tokens, output_tokens, "
            "cache_read_tokens) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                new_id(),
                aid,
                question,
                out["answer"],
                now_iso(),
                src,
                out.get("input_tokens"),
                out.get("output_tokens"),
                out.get("cache_read_tokens"),
            ),
        )
    return AskResponse(answer=out["answer"], remaining=MAX_ASKS - len(prev) - 1, source=src)


# ------------------------------------------------------------------ summary
def summary(sid: str) -> AssessmentSummary:
    """Session summary for every mode. Practice/drill/review: any time, over the attempts submitted so far.
    Assessment: 409 until every case is submitted (nothing is revealed before that)."""
    from backend.app.analytics.learner import case_level_stats, miss_counts

    repo = get_repo()
    with tx() as con:
        s = _session(con, sid)
        atts = rows(con, "SELECT * FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL ORDER BY idx", sid)
    total = session_total(repo, s)
    if is_assessment(s["mode"]) and len(atts) < (total or 0):
        raise HTTPException(status_code=409, detail=f"assessment in progress ({len(atts)}/{total})")
    recs = [parse_attempt(a, repo) for a in atts]
    st = case_level_stats(recs)
    cases = []
    for a, r in zip(atts, recs, strict=True):
        c = repo.get(r["case_id"])
        findings = c.findings if c else []
        res = {o["target"]: o["result"] for o in r["outcomes"]}
        mc = miss_counts(r)
        labels = list(dict.fromkeys(f.label for f in findings))
        cases.append(
            {
                "attempt_id": r["id"],
                "case_id": r["case_id"],
                "index": a["idx"] + 1,
                "score": r["score"],
                "success": r["success"],
                "is_normal": c.is_normal if c else None,
                "labels": labels,
                "label_displays": [config.display(lab) for lab in labels],
                "miss_types": [b for b in MISS_BUCKETS if mc.get(b)],
                "n_findings": len(findings),
                "n_found": sum(res.get(f.short_id) in FOUND_RESULTS for f in findings),
                "n_false_positives": sum(o["result"] == "false_positive" for o in r["outcomes"]),
                "outcomes": r["outcomes"],
                "findings": [
                    {
                        "finding_id": f.short_id,
                        "label": f.label,
                        "display": config.display(f.label),
                        "kind": f.kind,
                        "side": f.side,
                        "primary_zone": f.primary_zone,
                        "relative_location": f.relative_location,
                        "bbox": list(f.geometry.bbox),
                    }
                    for f in findings
                ],
            }
        )
    return AssessmentSummary(
        session_id=sid,
        mode=s["mode"],
        n_cases=len(recs),
        n_abnormal=st["n_abnormal"],
        n_normal=st["n_normal"],
        n_focal_findings=st["n_focal_findings"],
        sensitivity=st["sensitivity"],
        specificity=st["specificity"],
        localization_fraction=st["localization_fraction"],
        false_positives_per_image=st["false_positives_per_image"],
        miss_type_mix=st["miss_type_mix"],
        score_mean=st["score_mean"],
        total=total,
        complete=total is not None and len(recs) >= total,
        cases=cases,
    )


def parse_attempt(a: dict, repo: CaseRepository | None = None) -> dict[str, Any]:
    repo = repo or get_repo()
    c = repo.get(a["case_id"])
    return {
        "id": a["id"],
        "learner_id": a["learner_id"],
        "session_id": a["session_id"],
        "case_id": a["case_id"],
        "mode": a["mode"],
        "submitted_at": a["submitted_at"],
        "score": a["score"] or 0.0,
        "success": bool(a["success"]),
        "declared_normal": bool(a["declared_normal"]),
        "normal_confidence": a["normal_confidence"],
        "outcomes": jload(a["outcomes_json"], []),
        "marks": jload(a["marks_json"], []),
        "search": jload(a["search_json"], {}),
        "hints_used": a["hints_used"],
        "is_normal": bool(c.is_normal) if c else False,
        "findings": [
            {
                "id": f.short_id,
                "label": f.label,
                "kind": f.kind,
                "centroid": list(f.centroid),
                "difficulty": f.difficulty,
            }
            for f in (c.findings if c else [])
        ],
        "b0": c.difficulty_prior if c else 0.0,
    }


# ------------------------------------------------------------------ "show anatomy" after submit
@functools.lru_cache(maxsize=64)
def _outlines_cached(root: str, case_id: str) -> dict[str, Any]:
    from backend.app.anatomy_outline import zone_outlines

    repo = get_repo(Path(root))
    zones, meta = repo.zones(case_id)
    return zone_outlines(zones, meta, config.zone_human, frozenset(config.review_area_ids()))


def anatomy(aid: str) -> dict[str, Any]:
    """Zone outlines for a SUBMITTED attempt (409 before; in assessment 409 until the session summary is available).
    Zones are derived from anatomy, not findings, but are still withheld before submit (ground-truth invariant)."""
    repo = get_repo()
    with tx() as con:
        a = _attempt(con, aid)
        if not a["submitted_at"]:
            raise HTTPException(status_code=409, detail="attempt not submitted")
        if assessment_locked(con, repo, a):
            raise HTTPException(status_code=409, detail="available after the assessment summary")
    if repo.get(a["case_id"]) is None:
        raise _404("case")
    return {"attempt_id": aid, "case_id": a["case_id"], **_outlines_cached(str(repo.root), a["case_id"])}
