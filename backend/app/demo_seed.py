"""`make demo` seeding (SPEC §17, M8): playlist check, demo learner + playlist session, debrief cache warm-up.

Usage:
  uv run python -m backend.app.demo_seed                 # offline (default): templates only, never the network
  uv run python -m backend.app.demo_seed --reset-db      # drop and recreate the DB first (wipes all attempts)
  uv run python -m backend.app.demo_seed --live          # live debriefs for the 6 rehearsed paths (needs a key and
                                                         # BLINDSPOT_OFFLINE=0; ~6 calls; human checkpoint first)

What it does:
1. Reads config/demo_playlist.yaml; every case must exist, be in the practice split and carry no QA flag outside
   the allowlist (adaptive.selector.BENIGN_FLAGS). Any problem → exit 1 before touching the DB.
2. Creates (or reuses) the learner "Demo" (participant_code DEMO) and a Practice session with settings
   {"playlist": [...]}: `/next` serves the playlist cases in order, then adaptive selection. Typing "Demo" on the
   onboarding page starts a new Practice session that inherits the playlist (services._demo_playlist_settings).
3. For each slot, builds the rehearsed read as a scripted submit (marks + telemetry), scores it with the real
   engine and generates its debrief through tutor_bridge. Live results are stored in the debriefs table under
   their §8.7 cache key (attempt_id "warm:<slot>:<case_id>", no attempt row, so dashboards never count them).
   The cache key covers case, model, prompt version, learner level, (target, result) pairs, FP zones and the
   unvisited review areas: the on-stage read hits the cache only if it reproduces those (printed below).

No attempts are written, so dashboards show only real reads (non-negotiable 4).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from backend.app import config, db, services, tutor_bridge
from backend.app.adaptive.selector import qa_ok
from backend.app.cases import CaseRepository, dilate, get_repo
from backend.app.engine import evaluate
from backend.app.settings import get_settings
from shared.contracts import (
    AttemptSubmit,
    Case,
    ClientTiming,
    Finding,
    Mark,
    PatternSelection,
    SessionCreate,
    TelemetryEvent,
)

PLAYLIST = config.CONFIG_DIR / "demo_playlist.yaml"
SCRIPTS = ("search_miss", "decision_miss", "find_all", "normal_call", "find_one")
VISIT_MS = 450.0  # per review area: comfortably above scoring.yaml dwell.visit_ms
STEP_MS = 33.0


@dataclass
class Slot:
    slot: int
    case_id: str
    story: str
    actions: str = ""
    script: str | None = None


@dataclass
class Rehearsal:
    submit: AttemptSubmit
    script: str
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ playlist
def load_playlist(path: Path = PLAYLIST) -> list[Slot]:
    d = yaml.safe_load(path.read_text()) or {}
    out = []
    for e in d.get("cases") or []:
        out.append(
            Slot(
                slot=int(e["slot"]),
                case_id=str(e["case_id"]),
                story=str(e.get("story", "")),
                actions=str(e.get("rehearsed_actions", "")),
                script=e.get("script"),
            )
        )
    return sorted(out, key=lambda s: s.slot)


def check_playlist(slots: list[Slot], repo: CaseRepository) -> list[str]:
    problems = []
    if not slots:
        problems.append("playlist is empty")
    seen: set[str] = set()
    for s in slots:
        c = repo.get(s.case_id)
        if s.case_id in seen:
            problems.append(f"slot {s.slot}: {s.case_id} appears twice")
        seen.add(s.case_id)
        if c is None:
            problems.append(f"slot {s.slot}: {s.case_id} not found in {repo.root}")
            continue
        if c.split != "practice":
            problems.append(f"slot {s.slot}: {s.case_id} is in split {c.split!r}, not practice")
        if not qa_ok(c.qa_flags):
            problems.append(f"slot {s.slot}: {s.case_id} has qa_flags {c.qa_flags}")
        if s.script is not None and s.script not in SCRIPTS:
            problems.append(f"slot {s.slot}: unknown script {s.script!r} (one of {', '.join(SCRIPTS)})")
    return problems


def infer_script(slot: Slot, case: Case) -> str:
    """Rehearsal script from an explicit `script:` key, else from the story wording (SPEC §17 stories)."""
    if slot.script:
        return slot.script
    if case.is_normal:
        return "normal_call"
    t = f"{slot.story} {slot.actions}".lower()
    if "satisfaction" in t or "find one" in t:
        return "find_one"
    if "decision" in t:
        return "decision_miss"
    if "search" in t:
        return "search_miss"
    return "find_all"


# ------------------------------------------------------------------ scripted reads (pure given the repo)
def interior_point(region: np.ndarray, avoid: np.ndarray | None = None) -> tuple[float, float] | None:
    """Most interior pixel of `region` minus `avoid` (max distance to the boundary), as (x, y)."""
    m = region if avoid is None else region & ~avoid
    if not m.any():
        return None
    dt = cv2.distanceTransform(np.pad(m, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    y, x = np.unravel_index(int(np.argmax(dt)), dt.shape)
    return float(x), float(y)


def _hover(x: float, y: float, ms: float, t0: float, w: int, h: int) -> list[TelemetryEvent]:
    out, t, k = [], t0, 0
    while t < t0 + ms:
        dx = 2.0 if k % 2 else -2.0
        out.append(
            TelemetryEvent(t=t, kind="move", x=min(w, max(0.0, x + dx)), y=y, zoom=1.0, vp=(0, 0, w, h), loupe=True)
        )
        t += STEP_MS
        k += 1
    return out


def _finding_mask(repo: CaseRepository, case: Case, f: Finding) -> np.ndarray:
    m = repo.mask(case.case_id, f.finding_id)
    if m is not None:
        return m
    m = np.zeros((case.height, case.width), bool)
    x0, y0, x1, y1 = (int(v) for v in f.geometry.bbox)
    m[max(0, y0) : y1 + 1, max(0, x0) : x1 + 1] = True
    return m


def rehearse(case: Case, script: str, repo: CaseRepository) -> Rehearsal:
    """Scripted read for one story. Telemetry hovers review-area interiors (≥ visit_ms) chosen away from findings
    the story wants missed, so the engine yields the story's outcome."""
    sc = config.scoring()
    w, h = case.width, case.height
    rho = int(round(float(sc["roi"]["roi_frac"]) * w))
    zones, _ = repo.zones(case.case_id)
    focal = [f for f in case.findings if f.kind == "focal"]
    pats = [f for f in case.findings if f.kind == "pattern"]
    rois = {f.short_id: dilate(_finding_mask(repo, case, f), rho + 4) for f in focal + pats}
    all_roi = np.zeros((h, w), bool)
    for r in rois.values():
        all_roi |= r
    target = min(focal, key=lambda f: f.area_frac) if focal else None
    keep = max(focal, key=lambda f: f.area_frac) if focal else None

    marks: list[Mark] = []
    patterns: list[PatternSelection] = []
    declared_normal = False
    normal_conf: int | None = None
    events: list[TelemetryEvent] = []
    notes: list[str] = []
    t = 0.0

    def visit(areas: list[str], avoid: np.ndarray | None, skip_touching: np.ndarray | None) -> None:
        nonlocal t
        for z in areas:
            zm = zones.get(z)
            if zm is None or zm.shape != (h, w):
                continue
            if skip_touching is not None and (zm & skip_touching).any():
                continue
            p = interior_point(zm, avoid)
            if p is None:
                continue
            seg = _hover(p[0], p[1], VISIT_MS, t, w, h)
            events.extend(seg)
            t = seg[-1].t + STEP_MS

    def mark_finding(f: Finding, mid: str) -> None:
        nonlocal t
        p = interior_point(_finding_mask(repo, case, f))
        if p is None:
            p = (float(f.centroid[0]), float(f.centroid[1]))
        seg = _hover(p[0], p[1], 700.0, t, w, h)
        events.extend(seg)
        t = seg[-1].t + STEP_MS
        marks.append(Mark(mark_id=mid, x=p[0], y=p[1], label=f.label, confidence=4))

    areas = config.review_area_ids()
    if script == "normal_call" or (script != "find_all" and not focal):
        visit(areas, None, None)
        declared_normal, normal_conf = True, 4
        if script != "normal_call":
            notes.append("no focal finding: rehearsed as a normal call")
    elif script == "find_all":
        visit(areas, None, None)
        for i, f in enumerate(focal, 1):
            mark_finding(f, f"M{i}")
        patterns = [PatternSelection(label=f.label, confidence=4) for f in pats]
    elif script == "find_one":
        assert keep is not None
        mark_finding(keep, "M1")
        notes.append(f"marks {keep.short_id} only, then stops")
    elif script == "search_miss":
        assert target is not None
        visit(areas, all_roi, rois[target.short_id])
        side = target.side if target.side in ("right", "left") else "right"
        lz = zones.get(f"{side}_lower_zone")
        p = interior_point(lz, all_roi) if lz is not None else None
        if p is not None:
            seg = _hover(p[0], p[1], 500.0, t, w, h)
            events.extend(seg)
            t = seg[-1].t + STEP_MS
            marks.append(Mark(mark_id="M1", x=p[0], y=p[1], label=target.label, confidence=3))
        notes.append(f"never enters {target.short_id} ({target.label}); marks the {side} lower zone")
    elif script == "decision_miss":
        assert target is not None
        visit(areas, all_roi, rois[target.short_id])
        p = interior_point(_finding_mask(repo, case, target))
        if p is not None:
            seg = _hover(p[0], p[1], 2200.0, t, w, h)
            events.extend(seg)
            t = seg[-1].t + STEP_MS
        declared_normal, normal_conf = True, 3
        notes.append(f"lingers on {target.short_id} ({target.label}), calls normal")
    else:
        raise ValueError(f"unknown script {script!r}")
    if events:
        events.append(TelemetryEvent(t=t, kind="leave", x=None, y=None, zoom=1.0, vp=(0, 0, w, h), loupe=True))
    secs = max(1, int(t / 1000) + 1)
    sub = AttemptSubmit(
        marks=[] if declared_normal else marks,
        patterns=[] if declared_normal else patterns,
        declared_normal=declared_normal,
        normal_confidence=normal_conf,
        telemetry=events,
        hints_used=0,
        client_timing=ClientTiming(
            shown_at="2026-10-08T18:00:00Z", submitted_at=f"2026-10-08T18:{secs // 60:02d}:{secs % 60:02d}Z"
        ),
    )
    return Rehearsal(sub, script, notes)


# ------------------------------------------------------------------ DB: demo learner + playlist session
def create_demo_session(case_ids: list[str], level: str) -> tuple[str, str]:
    created = services.create_session(
        SessionCreate(
            display_name="Demo",
            level=level,  # type: ignore[arg-type]
            participant_code=services.DEMO_CODE,
            mode="practice",
            settings={"playlist": case_ids, "projector": True, "demo": True},
        )
    )
    return created.session_id, created.learner_id


def _empty_history(labels: list[str]) -> dict[str, Any]:
    h: dict[str, Any] = {lab: {"attempts": 0, "localized": 0} for lab in labels}
    h["recent_miss_types"] = {"search": 0, "recognition": 0, "decision": 0}
    return h


def warm_one(slot: Slot, case: Case, repo: CaseRepository, *, level: str, offline: bool) -> dict[str, Any]:
    """Score the rehearsed read and generate its debrief; persist live/cached output under its cache key."""
    reh = rehearse(case, infer_script(slot, case), repo)
    ev = evaluate(case, reh.submit, repo, hints_used=0)
    res = {
        "script": reh.script,
        "notes": reh.notes,
        "outcomes": [f"{o.target}:{o.result}" for o in ev.outcomes],
        "unvisited": list(ev.facts_search.unvisited_review_areas),
        "score": ev.score,
    }
    facts = tutor_bridge.build_facts(
        case=case,
        submit=reh.submit,
        outcomes=ev.outcomes,
        spatial_relations=ev.spatial_relations,
        search=ev.facts_search,
        mark_zones=ev.mark_zones,
        level=level,
        history=_empty_history(sorted({f.label for f in case.findings})),
    )
    if facts is None:
        res["cache"] = "FAILED: tutor facts unavailable"
        return res
    aid = f"warm:{slot.slot}:{case.case_id}"
    out = tutor_bridge.generate_debrief(
        facts, case, attempt_id=aid, submit=reh.submit, offline=offline, cache_get=services._cache_get
    )
    if out is None:
        res["cache"] = "FAILED: tutor returned nothing"
        return res
    v = out.get("validator") or {}
    bad = "" if v.get("ok", True) else ", INVALID"
    src = out.get("source")
    res["cache_key"] = out.get("cache_key")
    if src == "live":
        with db.tx() as con:
            con.execute(
                "INSERT INTO debriefs(id, attempt_id, cache_key, model, prompt_version, facts_json, output_json, "
                "validator_json, source, latency_ms, input_tokens, output_tokens, created_at, status, provenance) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'ready', ?)",
                (
                    db.new_id(),
                    aid,
                    out.get("cache_key"),
                    out.get("model"),
                    out.get("prompt_version"),
                    facts.model_dump_json(by_alias=True),
                    out["debrief"].model_dump_json(),
                    json.dumps(v),
                    "live",
                    out.get("latency_ms"),
                    out.get("input_tokens"),
                    out.get("output_tokens"),
                    db.now_iso(),
                    out.get("provenance"),
                ),
            )
        res["cache"] = f"warmed: live{bad}"
    elif src == "cache":
        res["cache"] = f"already warm{bad}"
    else:
        reason = v.get("fallback_reason") or "template"
        res["cache"] = f"template: {reason}, not cached{bad}"
    return res


# ------------------------------------------------------------------ CLI
def _row(cols: list[str], widths: list[int]) -> str:
    return "  ".join(c[:wd].ljust(wd) for c, wd in zip(cols, widths, strict=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed the demo playlist and warm the debrief cache (SPEC §17).")
    ap.add_argument("--reset-db", action="store_true", help="drop and recreate the SQLite DB first")
    ap.add_argument("--live", action="store_true", help="generate live debriefs (needs key, BLINDSPOT_OFFLINE=0)")
    ap.add_argument("--level", default="MS3", help="demo learner level (part of the cache key); default MS3")
    ap.add_argument("--playlist", type=Path, default=PLAYLIST)
    a = ap.parse_args(argv)

    s = get_settings()
    repo = get_repo()
    slots = load_playlist(a.playlist)
    problems = check_playlist(slots, repo)
    if problems:
        print("demo playlist check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    if a.reset_db:
        db.reset()
        print(f"reset {s.db_path}")
    live = a.live and not s.offline
    if a.live and not live:
        print("--live ignored: no ANTHROPIC_API_KEY or BLINDSPOT_OFFLINE=1 → templates only")
    if live:
        print(f"LIVE: up to {2 * len(slots)} Claude calls (model from BLINDSPOT_MODEL_DEBRIEF)")
    sid, lid = create_demo_session([sl.case_id for sl in slots], a.level)

    widths = [4, 10, 34, 30, 44, 34]
    print(_row(["slot", "case_id", "story", "findings", "rehearsed outcomes", "cache"], widths))
    print(_row(["-" * w for w in widths], widths))
    details = []
    failed = False
    for sl in slots:
        case = repo.get(sl.case_id)
        assert case is not None
        res = warm_one(sl, case, repo, level=a.level, offline=not live)
        failed |= res["cache"].startswith("FAILED") or "INVALID" in res["cache"]
        finds = ", ".join(f"{f.short_id} {f.label}" for f in case.findings) or "normal"
        print(_row([str(sl.slot), sl.case_id, sl.story, finds, " ".join(res["outcomes"]), res["cache"]], widths))
        details.append((sl, res))
    print()
    print("rehearsal scripts (an on-stage read hits the cache only with the same outcomes and unvisited areas):")
    for sl, res in details:
        note = "".join(f"{n}. " for n in res["notes"])
        unv = ", ".join(res["unvisited"]) or "none"
        print(f"  slot {sl.slot} [{res['script']}] score {res['score']:.0f}. {note}unvisited: {unv}")
    print()
    print(f"db: {s.db_path}")
    print(f'demo learner: {lid} (type "Demo" on the onboarding page; Practice serves the playlist in order)')
    print(f"demo session: {sid}  (GET /api/sessions/{sid}/next)")
    print(f"mode: {'live' if live else 'offline (templates)'}; /api/dev is {'ON' if s.blindspot_dev else 'off'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
