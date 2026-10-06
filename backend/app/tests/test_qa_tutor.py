"""QA: offline tutor on REAL cases (skipped when data/processed is absent) and on fixtures through the API.

Owner: qa-reviewer. Independent checks (not just the tutor's own validator): banned/management terms, cm/mm,
finding ids vs outcomes, results copied from FACTS, patient-side wording, schema validity of the HTTP response.
No Anthropic API: offline=True and an autouse guard that makes constructing an SDK client fail.
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.app.cases import CaseRepository
from backend.app.engine import evaluate
from backend.app.tests.conftest import FIXTURES, chain, hover, make_submit, mark
from backend.app.tutor.facts import build_facts
from backend.app.tutor.service import generate_debrief
from backend.app.tutor.validator import validate
from shared.contracts import Case, DebriefOutput, PatternSelection

REAL = Path(__file__).resolve().parents[3] / "data" / "processed"
SCHEMAS = Path(__file__).resolve().parents[3] / "shared" / "schemas"

MANAGEMENT = re.compile(
    r"\b(treat\w*|manage\w*|antibiotic\w*|chest tube|drain\w*|biopsy|admit\w*|urgent\w*|emergen\w*|follow[- ]?up|"
    r"refer\w*|surg\w*|prognos\w*|medicat\w*|therap\w*|recommend\w*|you should (get|have|see)|call (a|your) doctor|"
    r"this patient|the patient has|diagnos(e|ed|is))\b",
    re.I,
)
UNITS = re.compile(r"\b\d+(?:\.\d+)?\s?(?:cm|mm|centimet\w+|millimet\w+)\b|\b(?:cm|mm)\b", re.I)
BANNED_DX = re.compile(r"\b(pneumonia|tuberculosis|\bTB\b|cancer|carcinoma|malignan\w*|covid\w*|sarcoid\w*)\b", re.I)


@pytest.fixture(autouse=True)
def _no_live_api(monkeypatch):
    import anthropic

    def boom(*a, **k):
        raise AssertionError("QA test attempted to construct a live Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


def _texts(out: DebriefOutput) -> list[str]:
    t = [out.headline, out.search_coaching, out.calibration_note, out.next_step]
    for f in out.findings:
        t += [f.where_to_look, f.why, *f.what_it_looks_like]
    for o in out.overcalls:
        t += [o.explanation, *o.possible_mimics]
    return t


def check_debrief(out: DebriefOutput, facts, label: str, allow_dx_words: set[str] = frozenset()) -> list[str]:
    errs: list[str] = []
    text = " \n ".join(_texts(out))
    if m := MANAGEMENT.search(text):
        errs.append(f"{label}: management/clinical phrasing '{m.group(0)}'")
    if (m := UNITS.search(text)) and facts.case.pixel_spacing_mm is None:
        errs.append(f"{label}: unit '{m.group(0)}' with unknown pixel spacing")
    if (m := BANNED_DX.search(text)) and m.group(0).lower() not in allow_dx_words:
        errs.append(f"{label}: diagnosis word '{m.group(0)}'")
    # finding ids match outcomes (non-mark targets)
    want = [
        o.target
        for o in facts.outcomes
        if o.result not in ("true_positive", "duplicate", "false_positive", "true_negative", "pattern_false")
    ]
    got = [f.finding_id for f in out.findings]
    if sorted(got) != sorted(want):
        errs.append(f"{label}: finding ids {got} != outcomes {want}")
    res = {o.target: o.result for o in facts.outcomes}
    for f in out.findings:
        if res.get(f.finding_id) != f.result:
            errs.append(f"{label}: {f.finding_id} result {f.result} != facts {res.get(f.finding_id)}")
    # overcall ids are false-positive marks
    fp = {o.target for o in facts.outcomes if o.result == "false_positive"}
    if {o.mark_id for o in out.overcalls} - fp:
        errs.append(f"{label}: overcall mark ids {[o.mark_id for o in out.overcalls]} not in {sorted(fp)}")
    # patient-side wording: a finding on the patient's LEFT must not be described as 'right' only (and vice versa)
    side = (
        {f.id if hasattr(f, "id") else f.finding_id: f.side for f in facts.case.findings} if facts.case.findings else {}
    )
    for f in out.findings:
        s = side.get(f.finding_id)
        w = f.where_to_look.lower()
        if s in ("right", "left"):
            other = "left" if s == "right" else "right"
            if re.search(rf"\b{other}\b", w) and not re.search(rf"\b{s}\b", w):
                errs.append(f"{label}: {f.finding_id} side {s} but where_to_look says {other}: {f.where_to_look!r}")
    if re.search(
        r"\b(image|screen|film) (left|right)\b|\b(left|right) (of|side of) the (image|screen|film)\b", text, re.I
    ):
        pass  # image-side wording is allowed only if explicit; validator R3 governs sentence laterality
    v = validate(out, facts)
    if not v.ok:
        errs.append(f"{label}: validator {v.errors}")
    return errs


def _script(case: Case, rng: random.Random):
    """Random learner behaviour covering every result type on this case. Returns AttemptSubmit."""
    related = {
        "consolidation": "atelectasis",
        "atelectasis": "consolidation",
        "nodule": "mass",
        "mass": "nodule",
        "effusion": "pleural_thickening",
        "pleural_thickening": "effusion",
        "calcification": "nodule",
    }
    focal = [f for f in case.findings if f.kind == "focal"]
    pats = [f for f in case.findings if f.kind == "pattern"]
    marks, tel, patterns, normal = [], [], [], False
    mode = rng.choice(["perfect", "related", "wrong", "miss_search", "miss_dwell", "normal_call", "overcall", "mixed"])
    n = 0
    for f in focal:
        cx, cy = f.centroid
        if mode == "perfect" or (mode == "mixed" and rng.random() < 0.5):
            n += 1
            marks.append(mark(f"M{n}", cx, cy, f.label, rng.randint(1, 5)))
            tel += hover(cx, cy, 800, t0=(tel[-1].t + 50) if tel else 0)
        elif mode == "related":
            n += 1
            marks.append(mark(f"M{n}", cx, cy, related.get(f.label, "not_sure"), 3))
            tel += hover(cx, cy, 700, t0=(tel[-1].t + 50) if tel else 0)
        elif mode == "wrong":
            n += 1
            marks.append(mark(f"M{n}", cx, cy, rng.choice(["pneumothorax", "fracture", "effusion"]), 2))
        elif mode == "miss_dwell":
            tel += hover(cx, cy, rng.choice([600, 2000]), t0=(tel[-1].t + 50) if tel else 0)
        elif mode == "mixed":
            pass
    if mode in ("overcall", "mixed"):
        n += 1
        marks.append(
            mark(f"M{n}", rng.uniform(100, case.width - 100), rng.uniform(100, case.height - 100), "nodule", 4)
        )
    if mode == "normal_call":
        normal = True
    for p in pats:
        if rng.random() < 0.6:
            patterns.append(PatternSelection(label=p.label, confidence=rng.randint(1, 5)))
    if mode == "overcall" and pats and rng.random() < 0.3:
        patterns.append(PatternSelection(label="emphysema", confidence=3))
    if case.is_normal and rng.random() < 0.7:
        normal, marks = (True, []) if mode != "overcall" else (False, marks)
    return make_submit(
        marks=marks,
        patterns=patterns,
        declared_normal=normal,
        normal_confidence=rng.randint(1, 5) if normal else None,
        telemetry=chain(tel) if tel else [],
        hints=rng.choice([0, 0, 1, 3]),
    )


def _run(case: Case, repo: CaseRepository, sub, level: str = "MS3"):
    ev = evaluate(case, sub, repo, hints_used=sub.hints_used)
    facts = build_facts(
        case=case,
        submit=sub,
        outcomes=ev.outcomes,
        spatial_relations=ev.spatial_relations,
        search=ev.facts_search,
        mark_zones=ev.mark_zones,
        level=level,
        history={},
    )
    out = generate_debrief(
        facts, case, attempt_id="qa", submit=sub, offline=True, cache_get=lambda k: None, client=None
    )
    return facts, out


def _check_cases(repo: CaseRepository, cases: list[Case], rng: random.Random) -> tuple[list[str], dict]:
    errs: list[str] = []
    stats = {"n": 0, "template": 0, "modes": {}}
    for case in cases:
        sub = _script(case, rng)
        facts, out = _run(case, repo, sub)
        stats["n"] += 1
        stats["template"] += out["source"] == "template"
        assert out["source"] in ("template", "cache"), out["source"]  # offline never live
        assert out["validator"]["ok"], out["validator"]
        errs += check_debrief(out["debrief"], facts, case.case_id)
    return errs, stats


def test_fixture_cases_offline_debriefs_pass_independent_checks():
    repo = CaseRepository(FIXTURES)
    rng = random.Random(7)
    errs: list[str] = []
    for _ in range(6):  # 6 random behaviours on each of the 10 SYNTHETIC cases
        e, st = _check_cases(repo, repo.all(), rng)
        errs += e
    assert not errs, "\n".join(errs[:20])


@pytest.mark.skipif(not (REAL / "cases.jsonl").exists(), reason="no real data in data/processed")
@pytest.mark.parametrize("seed", [int(os.environ.get("QA_SEED", "20261005")), 1, 2])
def test_real_cases_random_20_offline_debriefs(seed):
    repo = CaseRepository(REAL)
    rng = random.Random(seed)
    pool = [c for c in repo.all()]
    cases = rng.sample(pool, 20)
    errs, stats = _check_cases(repo, cases, rng)
    assert stats["n"] == 20
    assert not errs, "\n".join(errs[:20])


def _debrief_validator() -> Draft202012Validator:
    reg = Registry()
    for f in SCHEMAS.glob("*.json"):
        doc = json.loads(f.read_text())
        res = Resource.from_contents(doc)
        reg = reg.with_resource(doc["$id"], res).with_resource(f.name, res)
    return Draft202012Validator(json.loads((SCHEMAS / "debrief_response.json").read_text()), registry=reg)


def test_debrief_endpoint_body_validates_against_json_schema(api_env):
    c = api_env()
    v = _debrief_validator()
    sid = c.post("/api/sessions", json={"display_name": "QA", "level": "MS3", "mode": "practice"}).json()["session_id"]
    seen_ready = 0
    for _ in range(10):
        n = c.get(f"/api/sessions/{sid}/next").json()
        sub = make_submit(declared_normal=True, normal_confidence=3, telemetry=chain(hover(70, 150, 900)))
        r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=json.loads(sub.model_dump_json()))
        assert r.status_code == 200
        d = c.get(f"/api/attempts/{n['attempt_id']}/debrief")  # TestClient runs BackgroundTasks before returning
        assert d.status_code == 200
        body = d.json()
        errs = sorted(v.iter_errors(body), key=str)
        assert not errs, [e.message for e in errs]
        if body["status"] == "ready":
            seen_ready += 1
            assert body["source"] in ("template", "cache") and body["provenance"] in (
                "ai_draft",
                "student_reviewed",
                "radiologist_reviewed",
            )
            assert body["validator"]["ok"] is True
    assert seen_ready == 10
