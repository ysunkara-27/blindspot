"""Round 4 (clinician feedback): sign annotations drawn on the reveal, free-drawn outline marks, sign schematics,
Radiopaedia links and the tutor's use of drawn signs. Synthetic fixtures only; no Anthropic calls."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from backend.app import config
from backend.app.engine import evaluate
from backend.app.scoring.outline import (
    DEFAULT_OUTLINE,
    normalize_mark,
    outline_cfg,
    outline_verdict,
    overlap_stats,
    polygon_centroid,
    polygon_problems,
    rasterize,
)
from backend.app.signs import (
    MAX_SIGNS,
    MAX_WORDS,
    SIGN_NAMES,
    check_sign,
    load_schematics,
    schematics_for_label,
    signs_for_case,
)
from backend.app.tests.conftest import FIXTURES, make_submit, mark
from backend.app.tutor.cards import load_cards, load_zone_mimics
from backend.app.tutor.facts import build_facts
from backend.app.tutor.templates import template_debrief
from backend.app.tutor.validator import validate, validate_ask
from shared.contracts import Mark, Sign, SignSchematic, SubmitResult

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "shared" / "schemas" / "submit_result.json").read_text())


def _session(c, mode="practice", **settings) -> str:
    r = c.post("/api/sessions", json={"display_name": "S4", "level": "other", "mode": mode, "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _next(c, sid: str) -> dict:
    r = c.get(f"/api/sessions/{sid}/next")
    assert r.status_code == 200, r.text
    return r.json()


def _square(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    return [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]


def _draw(mid: str, poly, label: str, conf: int = 4) -> Mark:
    return Mark(mark_id=mid, x=0, y=0, label=label, confidence=conf, polygon=poly, tool="draw")


# ------------------------------------------------------------------ 1. sign engine per label (fixtures)
@pytest.mark.parametrize(
    "case_id,fid,expected",
    [
        ("syn_001", "F1", {"F1:round_opacity"}),
        ("syn_002", "F1", {"F1:pleural_line", "F1:no_markings"}),
        ("syn_003", "F1", {"F1:meniscus", "F1:blunted_angle"}),
        ("syn_004", "F1", {"F1:opacity"}),
        ("syn_005", "F1", {"F1:round_opacity"}),
        ("syn_006", "F2", {"F2:meniscus", "F2:blunted_angle"}),
        ("syn_007", "F1", {"F1:ctr_heart", "F1:ctr_chest"}),
        ("vol_001", "F1", {"F1:lesion", "F1:pointer"}),
        ("vol_003", "F1", {"F1:lesion", "F1:pointer", "F1:enhancing"}),
    ],
)
def test_signs_per_label_on_fixtures(repo, case_id, fid, expected):
    case = repo.get(case_id)
    signs = signs_for_case(case, repo)[fid]
    assert {s.id for s in signs} == expected
    assert len(signs) <= MAX_SIGNS
    for s in signs:
        assert check_sign(s) == [], check_sign(s)
        assert len(s.text.split()) <= MAX_WORDS
        assert " cm" not in s.text and " mm" not in s.text
        assert s.id == f"{fid}:{s.id.split(':')[1]}" and s.name


def test_sign_geometry_sits_on_the_finding(repo):
    case = repo.get("syn_001")
    f = case.findings[0]  # nodule at (70, 150)
    (s,) = signs_for_case(case, repo)["F1"]
    (cx, cy) = s.geometry.points[0]
    assert abs(cx - f.centroid[0]) < 2 and abs(cy - f.centroid[1]) < 2 and s.geometry.radius > 7
    assert s.geometry.plane is None and s.geometry.slice is None
    assert s.schematic is None  # nodule: no schematic; mass adds mass_vs_nodule
    (m,) = [x for x in signs_for_case(repo.get("syn_005"), repo)["F1"]]
    assert m.schematic == "mass_vs_nodule"


def test_pneumothorax_arrow_points_laterally_patient_side(repo):
    case = repo.get("syn_002")  # left upper zone → image right half; lateral = +x
    signs = {s.id: s for s in signs_for_case(case, repo)["F1"]}
    tail, head = signs["F1:no_markings"].geometry.points
    assert head[0] > tail[0] and head[1] == tail[1]
    assert signs["F1:pleural_line"].schematic == "visceral_pleural_line"
    assert signs["F1:pleural_line"].name == SIGN_NAMES["pleural_line"] == "Visceral pleural line"


def test_cardiomegaly_segments_and_ctr_text(repo):
    case = repo.get("syn_007")
    signs = signs_for_case(case, repo)["F1"]
    heart, chest = signs
    assert heart.geometry.kind == chest.geometry.kind == "segment"
    hw = heart.geometry.points[1][0] - heart.geometry.points[0][0]
    tw = chest.geometry.points[1][0] - chest.geometry.points[0][0]
    assert 0 < hw < tw
    assert f"= {case.cardiothoracic_ratio:.2f}" in heart.text and "PA vs AP not recorded" in heart.text


def test_volume_signs_are_on_the_measure_slice(repo):
    case = repo.get("vol_003")
    signs = signs_for_case(case, repo)["F1"]
    assert all(s.geometry.plane == "axial" and s.geometry.slice == case.findings[0].measure.slice for s in signs)
    lesion = signs[0]
    nz, ny, nx = case.volume.shape
    cx, cy = lesion.geometry.points[0]
    assert 0 <= cx < nx and 0 <= cy < ny and lesion.schematic == "mr_ring_enhancement"
    tail, head = signs[1].geometry.points
    assert 0 <= tail[0] <= nx - 1 and 0 <= tail[1] <= ny - 1  # arrow starts inside the slice


def test_normal_case_has_no_signs(repo):
    assert signs_for_case(repo.get("syn_008"), repo) == {}


# ------------------------------------------------------------------ 2. reveal + facts
def test_reveal_carries_signs_and_facts_card_says_look_for(repo):
    case = repo.get("syn_002")
    ev = evaluate(case, make_submit(), repo)
    (rf,) = ev.reveal.findings
    assert rf.signs and rf.signs[0].id == "F1:pleural_line"
    assert ev.signs_drawn == {"F1": ["Visceral pleural line", "Air beyond the lung edge"]}
    look = [ln for ln in ev.facts_card.lines if ln.startswith("Look for: ")]
    assert look == ["Look for: Visceral pleural line — A thin white line parallel to the chest wall: the visceral pleura."]
    assert ev.facts_card.lines.index(look[0]) == 1  # right after the missed finding's line


def test_found_finding_gets_no_look_for_line(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit(marks=[mark("M1", 70, 150, "nodule")]), repo)
    assert ev.reveal.findings[0].signs  # drawn anyway
    assert not any(ln.startswith("Look for") for ln in ev.facts_card.lines)


def test_facts_finding_signs_drawn(repo):
    case = repo.get("syn_003")
    sub = make_submit()
    ev = evaluate(case, sub, repo)
    facts = build_facts(
        case=case,
        submit=sub,
        outcomes=ev.outcomes,
        spatial_relations=ev.spatial_relations,
        search=ev.facts_search,
        signs_drawn=ev.signs_drawn,
    )
    assert facts.case.findings[0].signs_drawn == ["Meniscus", "Blunted costophrenic angle"]
    assert "signs_drawn" in facts.model_dump_json(by_alias=True)


# ------------------------------------------------------------------ 3. free-drawn outlines
def test_outline_helpers():
    sq = _square(10, 10, 5)
    assert polygon_centroid(sq) == (10.0, 10.0)
    assert polygon_centroid([(0, 0), (4, 0), (2, 0)]) == (2.0, 0.0)  # degenerate → vertex mean
    m = rasterize(sq, 30, 30)
    assert 100 <= m.sum() <= 130 and m[10, 10] and not m[25, 25]
    cfg = outline_cfg(config.scoring())
    assert cfg["iou_hit"] == 0.1 and cfg["on_target_iou"] == 0.3 and cfg["too_broad_factor"] == 8
    assert outline_cfg(None) == {k: float(v) for k, v in DEFAULT_OUTLINE.items()}
    f = np.zeros((30, 30), bool)
    f[5:16, 5:16] = True
    st = overlap_stats(m, f)
    assert st["iou"] > 0.3 and outline_verdict(st, False, cfg) == "on_target"
    big = np.zeros((60, 60), bool)
    big[0:40, 0:40] = True  # 1600 px around a 121 px finding: > 8 × its area
    st2 = overlap_stats(big, np.pad(f, ((0, 30), (0, 30))))
    assert st2["cover_frac"] == 1.0 and outline_verdict(st2, True, cfg) == "too_broad"
    assert outline_verdict(overlap_stats(rasterize(_square(15, 15, 14), 30, 30), f), True, cfg) == "partly"  # < 8 ×
    st3 = overlap_stats(rasterize(_square(24, 24, 4), 30, 30), f)
    assert outline_verdict(st3, False, cfg) == "off"
    assert polygon_problems(None, 100, 100, 400, "M1") == []
    assert polygon_problems([(1, 1), (2, 2)], 100, 100, 400, "M1")
    assert polygon_problems([(1, 1), (2, 2), (300, 3)], 100, 100, 400, "M1")
    assert polygon_problems([(i, i) for i in range(50)], 100, 100, 10, "M1")
    assert polygon_problems([(1, 1), (float("nan"), 2), (3, 3)], 100, 100, 400, "M1")


def test_normalize_mark_sets_centroid_and_tool():
    m = normalize_mark(Mark(mark_id="M1", x=0, y=0, label="nodule", confidence=3, polygon=_square(70, 150, 10)))
    assert (m.x, m.y, m.tool) == (70.0, 150.0, "draw")
    p = normalize_mark(Mark(mark_id="M2", x=5, y=6, label="nodule", confidence=3))
    assert (p.x, p.y, p.tool) == (5.0, 6.0, None)


def test_drawn_outline_scored_on_target_partly_and_off(repo):
    case = repo.get("syn_001")  # nodule r≈7 at (70, 150)
    ev = evaluate(case, make_submit(marks=[_draw("M1", _square(70, 150, 9), "nodule")]), repo)
    (rm,) = ev.reveal.marks
    assert rm.result == "true_positive" and rm.outline_verdict == "on_target" and rm.polygon is not None
    assert ev.outcomes[0].result == "found"
    # an outline whose centroid misses but which overlaps ≥ 10 % IoU still counts (looser rule) → partly
    ev2 = evaluate(case, make_submit(marks=[_draw("M1", _square(78, 150, 8), "nodule")]), repo)
    (rm2,) = ev2.reveal.marks
    assert rm2.result == "true_positive" and rm2.outline_verdict == "partly"
    # far away → false positive, off
    ev3 = evaluate(case, make_submit(marks=[_draw("M1", _square(200, 60, 8), "nodule")]), repo)
    (rm3,) = ev3.reveal.marks
    assert rm3.result == "false_positive" and rm3.outline_verdict == "off"


def test_drawn_outline_too_broad(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit(marks=[_draw("M1", _square(100, 150, 60), "nodule")]), repo)
    (rm,) = ev.reveal.marks
    # covers the whole nodule but is > 8 × its area: not a hit by any rule (centroid misses, IoU tiny, little of the
    # polygon lies on the nodule) → false positive, and the verdict says why
    assert rm.result == "false_positive" and rm.outline_verdict == "too_broad"
    assert ev.outcomes[0].result.startswith("missed_")
    evp = evaluate(case, make_submit(marks=[mark("M1", 100, 150, "nodule")]), repo)
    assert evp.reveal.marks[0].result == "false_positive" and evp.reveal.marks[0].outline_verdict is None


def test_drawn_outline_on_a_volume_slice(repo):
    case = repo.get("vol_001")  # pancreatic tumour, measure slice 8, centroid3 (24, 36, 8)
    f = case.findings[0]
    poly = _square(f.centroid3[0], f.centroid3[1], 6)
    m = Mark(mark_id="M1", x=0, y=0, label="pancreatic_tumour", confidence=4, plane="axial", slice=8, polygon=poly, tool="draw")
    ev = evaluate(case, make_submit(marks=[m]), repo)
    (rm,) = ev.reveal.marks
    assert rm.result == "true_positive" and rm.outline_verdict in ("on_target", "partly") and rm.slice == 8
    assert ev.reveal.findings[0].signs and ev.reveal.findings[0].signs[0].geometry.slice == 8


def test_submit_rejects_bad_polygons_and_returns_verdict_in_api(api_env):
    c = api_env()
    if True:
        sid = _session(c)
        n = _next(c, sid)
        aid = n["attempt_id"]
        base = make_submit().model_dump(mode="json")
        bad = {**base, "marks": [{"mark_id": "M1", "x": 1, "y": 1, "label": "nodule", "confidence": 3, "polygon": [[1, 1], [2, 2]], "tool": "draw"}]}
        assert c.post(f"/api/attempts/{aid}/submit", json=bad).status_code == 422
        out = {**base, "marks": [{"mark_id": "M1", "x": 1, "y": 1, "label": "nodule", "confidence": 3, "polygon": [[1, 1], [2, 2], [900, 3]], "tool": "draw"}]}
        assert c.post(f"/api/attempts/{aid}/submit", json=out).status_code == 422
        many = {**base, "marks": [{"mark_id": "M1", "x": 1, "y": 1, "label": "nodule", "confidence": 3, "polygon": [[i % 200, i % 100] for i in range(401)], "tool": "draw"}]}
        assert c.post(f"/api/attempts/{aid}/submit", json=many).status_code == 422
        notool = {**base, "marks": [{"mark_id": "M1", "x": 1, "y": 1, "label": "nodule", "confidence": 3, "tool": "draw"}]}
        assert c.post(f"/api/attempts/{aid}/submit", json=notool).status_code == 422
        good = {**base, "marks": [{"mark_id": "M1", "x": 0, "y": 0, "label": "nodule", "confidence": 3, "polygon": _square(70, 150, 9), "tool": "draw"}]}
        r = c.post(f"/api/attempts/{aid}/submit", json=good)
        assert r.status_code == 200, r.text
        res = SubmitResult.model_validate(r.json())
        rm = res.reveal.marks[0]
        assert rm.polygon is not None and rm.outline_verdict in ("on_target", "partly", "too_broad", "off")
        assert all(f.signs is not None for f in res.reveal.findings if f.kind == "focal")
        body = r.json()
        for f in body["reveal"]["findings"]:
            for s in f.get("signs") or []:
                assert set(s) >= {"id", "name", "text", "geometry"}
                assert set(SCHEMA["$defs"]["Sign"]["properties"]) >= set(s)


def test_signs_never_leak_before_submit(api_env):
    c = api_env()
    sid = _session(c)
    for _ in range(3):
        n = _next(c, sid)
        assert "signs" not in json.dumps(n) and "signs_drawn" not in json.dumps(n)
        r = c.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []})
        assert r.status_code == 200 and "sign" not in r.text.lower()
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=make_submit().model_dump(mode="json"))


# ------------------------------------------------------------------ 4. schematics + endpoints + reference
def test_schematic_yaml_validates_against_contract():
    d = config.signs_dir()
    files = sorted(d.glob("*.yaml"))
    assert len(files) >= 12
    seen = set()
    for p in files:
        doc = yaml.safe_load(p.read_text())
        s = SignSchematic.model_validate(doc)
        assert s.id == p.stem and s.id not in seen
        seen.add(s.id)
        assert len(s.description.split()) <= 40, s.id
        assert s.svg.startswith("<svg") and 'viewBox="0 0 200 200"' in s.svg and "<text" not in s.svg
        assert len(s.svg.encode()) <= 3072, s.id
        assert s.review_status == "ai_draft" and s.modality in ("cxr", "ct", "mr")
        for lab in s.labels:
            assert lab in config.labels(), (s.id, lab)
        assert s.radiopaedia_url is None or s.radiopaedia_url.startswith("https://radiopaedia.org/articles/")
    for must in (
        "visceral_pleural_line", "deep_sulcus", "meniscus_sign", "silhouette_sign", "air_bronchogram", "bat_wing",
        "kerley_b_lines", "cardiothoracic_ratio", "mass_vs_nodule", "rib_fracture_cortex", "pleural_thickening_band",
        "ct_hypoenhancing_mass", "mr_ring_enhancement", "mr_vasogenic_oedema",
    ):
        assert must in seen
    sch = load_schematics()
    assert sch["bat_wing"].labels == [] and sch["bat_wing"].modality == "cxr"
    assert schematics_for_label("pneumothorax") == ["visceral_pleural_line", "deep_sulcus"]
    assert schematics_for_label("brain_tumour") == ["mr_ring_enhancement", "mr_vasogenic_oedema"]


def test_every_schematic_referenced_by_the_engine_exists():
    from backend.app.signs import SCHEMATICS

    sch = load_schematics()
    assert set(SCHEMATICS.values()) <= set(sch)


def test_signs_endpoints_and_reference_signs(api_env):
    c = api_env()
    if True:
        r = c.get("/api/signs")
        assert r.status_code == 200 and len(r.json()) >= 12
        one = c.get("/api/signs/meniscus_sign")
        assert one.status_code == 200 and one.json()["labels"] == ["effusion"] and one.json()["svg"].startswith("<svg")
        assert c.get("/api/signs/not_a_sign").status_code == 404
        ref = c.get("/api/reference/effusion")
        assert ref.status_code == 200 and ref.json()["signs"] == ["meniscus_sign"]
        bank = c.get("/api/reference").json()
        by = {lab["label"]: lab["signs"] for lab in bank["labels"]}
        assert by["pneumothorax"] == ["visceral_pleural_line", "deep_sulcus"] and by["calcification"] == []


# ------------------------------------------------------------------ 5. Radiopaedia links on the cards
def test_every_card_has_a_canonical_radiopaedia_url_and_a_check_note():
    cards = load_cards()
    assert len(cards) == 18
    for lab, c in cards.items():
        assert c.radiopaedia_url and c.radiopaedia_url.startswith("https://radiopaedia.org/articles/"), lab
        slug = c.radiopaedia_url.rsplit("/", 1)[1]
        assert slug and slug == slug.lower() and " " not in slug
        assert "radiopaedia_url checked 2026-10-07" in (c.review.notes or ""), lab
        assert f"/articles/{slug}" in (c.review.notes or ""), lab


# ------------------------------------------------------------------ 6. tutor: templates, validator R10, ask
def _facts(repo, case_id, sub=None):
    case = repo.get(case_id)
    sub = sub or make_submit()
    ev = evaluate(case, sub, repo)
    return build_facts(
        case=case,
        submit=sub,
        outcomes=ev.outcomes,
        spatial_relations=ev.spatial_relations,
        search=ev.facts_search,
        signs_drawn=ev.signs_drawn,
    )


def test_template_mentions_the_first_drawn_sign_and_validates(repo):
    facts = _facts(repo, "syn_002")
    out = template_debrief(facts)
    assert out.findings[0].what_it_looks_like[0] == "Look at the visceral pleural line drawn on the film"
    v = validate(out, facts)
    assert v.ok, v.errors
    vol = _facts(repo, "vol_003")
    outv = template_debrief(vol)
    assert outv.findings[0].what_it_looks_like[0] == "Look at the lesion outline drawn on the slice"
    assert validate(outv, vol).ok


def test_validator_r10_rejects_signs_not_drawn_but_allows_drawn_and_card_signs(repo):
    facts = _facts(repo, "syn_001")  # nodule: drawn sign "Round opacity" (generic, not in the lexicon)
    out = template_debrief(facts)
    bad = out.model_copy(update={"search_coaching": "Look for the visceral pleural line next time."})
    v = validate(bad, facts)
    assert any(e.startswith("R10") and "Visceral pleural line" in e for e in v.errors), v.errors
    ptx = _facts(repo, "syn_002")
    good = template_debrief(ptx).model_copy(update={"search_coaching": "Look at the visceral pleural line drawn."})
    assert validate(good, ptx).ok
    # a sign the card itself names (silhouette sign on the consolidation card) is allowed without being drawn
    cons = _facts(repo, "syn_004")
    ok = template_debrief(cons).model_copy(update={"search_coaching": "Watch for a silhouette sign at the heart."})
    assert validate(ok, cons).ok, validate(ok, cons).errors


def test_ask_what_sign_should_i_look_for_names_the_drawn_sign(repo):
    from backend.app.tutor.ask import template_answer

    facts = _facts(repo, "syn_003")
    a = template_answer("What sign should I look for?", facts, load_cards(), load_zone_mimics())
    assert a.startswith("Look at the meniscus drawn beside F1 on the film; start there.")
    assert validate_ask(a, facts).ok, validate_ask(a, facts).errors
    bad = "Look for the deep sulcus sign at the base."
    assert any(e.startswith("R10") for e in validate_ask(bad, facts).errors)


def test_prompt_v5_has_the_drawn_sign_rule():
    from backend.app.tutor.prompts import load_prompt

    p = load_prompt("debrief_system")
    assert p.version == "v5" and "signs_drawn" in p.text and "never invent other signs" in p.text.lower()
    a = load_prompt("ask_system")
    assert a.version == "v3" and "signs_drawn" in a.text


def test_sign_contract_roundtrip():
    s = Sign(id="F1:x", name="X", text="t", geometry={"kind": "circle", "points": [(1, 2)], "radius": 3})
    assert Sign.model_validate_json(s.model_dump_json()) == s
    assert FIXTURES.exists()
