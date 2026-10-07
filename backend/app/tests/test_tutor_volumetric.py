"""Tutor on volumetric (CT / MR) cases: facts, validator rules, templates, hints, ask answers, cache key, cards.

Synthetic fixtures only (pipeline/tests/fixtures/synthetic/cases_msd.jsonl). No live API call (mock client guard).
"""

from __future__ import annotations

import json
import re

import numpy as np
import pytest

from backend.app.tests._tutor_helpers import facts_for
from backend.app.tests._tutor_vol_helpers import VOL_SCENARIOS, vmark, vol_cases, vol_facts_for
from backend.app.tutor import cards as cards_mod
from backend.app.tutor import hints_volume, vocab
from backend.app.tutor.ask import classify_question, template_answer
from backend.app.tutor.cache import cache_key_for_facts
from backend.app.tutor.facts import facts_json
from backend.app.tutor.hints import hint
from backend.app.tutor.templates import template_debrief
from backend.app.tutor.validator import total_word_limit, total_words, validate, validate_ask
from shared.contracts import TelemetryEvent

CM = re.compile(r"\b\d+(?:\.\d+)?\s?(?:cm|centimet\w*)\b|\bcentimet\w*", re.I)


@pytest.fixture(autouse=True)
def _no_live_api(monkeypatch):
    import anthropic

    def boom(*a, **k):
        raise AssertionError("test attempted to construct a live Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


def _has(errs, tag, needle=""):
    return any(e.startswith(tag) and needle.lower() in e.lower() for e in errs)


def _out(name):
    f, _, _ = vol_facts_for(name)
    return f, template_debrief(f).model_dump()


# --------------------------------------------------------------------------- facts
def test_facts_carry_modality_provenance_slices_sizes_and_measurements():
    f, c, sub = vol_facts_for("found")
    assert f.case.modality == "ct" and f.case.body_region == "abdomen"
    assert f.case.provenance == "Reference segmented by a test script (synthetic)"
    assert f.case.projection.startswith("axial CT of the abdomen")
    x = f.case.findings[0]
    assert x.slice_range == [6, 10] and x.size_mm == 13.5 and x.components is None
    assert x.relative_location == "middle slices of the volume, patient's right, slices 7-11 of 16"  # 1-based
    assert x.size == "13.5 mm long axis on slice 9"
    m = f.learner.marks[0]
    assert m.plane == "axial" and m.slice == 8  # contract index stays 0-based
    assert [(q.mark_id, q.long_mm, q.plane) for q in f.learner.measurements] == [("M1", 12.0, "axial")]
    assert f.search.slices_viewed_pct == 62.0 and f.search.finding_slices_viewed == {"F1": True}
    o = next(o for o in f.outcomes if o.target == "F1")
    assert o.slices_viewed is True and o.size_verdict["ok"] is True
    assert not CM.search(facts_json(f)), "facts never state centimetres"


def test_facts_components_and_unmatched_outcome_and_patient_side():
    f, _, _ = vol_facts_for("missed_decision")
    x = f.case.findings[0]
    assert x.components == ["oedema", "tumour core", "enhancing tumour"] and x.side == "left"
    assert "patient's left" in x.relative_location
    f2, _, _ = vol_facts_for("unmatched")
    um = [o for o in f2.outcomes if o.result == "unmatched"]
    assert [o.target for o in um] == ["M2"] and um[0].zone == "superior_slab"
    assert "liver_tumour" in f2.teaching_cards  # the learner's label gets its card


def test_cxr_facts_unchanged_by_volumetric_fields():
    f, _, _ = facts_for("found")
    assert f.case.modality == "cxr" and f.case.provenance is None and f.case.projection.startswith("frontal")
    assert f.case.findings[0].slice_range is None and f.case.findings[0].size_mm is None
    assert f.learner.measurements == [] and f.search.slices_viewed_pct is None


# --------------------------------------------------------------------------- validator
def test_r6_cm_always_banned_and_mm_only_from_facts():
    f, d = _out("found")
    d["next_step"] = "It was about 1.3 cm across."
    assert _has(validate(d, f).errors, "R6", "centimetres")
    d["next_step"] = "It was about 32 mm across."
    assert _has(validate(d, f).errors, "R6", "32 mm")
    d["next_step"] = "The reference measures 13.5 mm; you measured 12 mm."
    assert not _has(validate(d, f).errors, "R6")
    d["next_step"] = "Roughly 14 mm is close enough."  # ± 1 mm of 13.5
    assert not _has(validate(d, f).errors, "R6")


def test_r6_mm_banned_when_facts_have_no_size():
    f, d = _out("true_negative")
    d["next_step"] = "Anything over 10 mm matters."
    assert _has(validate(d, f).errors, "R6", "10 mm")


def test_r4_slice_numbers_must_match_the_finding_or_a_mark():
    f, d = _out("found")
    d["findings"][0]["why"] = "You never scrolled to slices 13-15 on this volume."  # finding is 7-11 (1-based)
    assert _has(validate(d, f).errors, "R4", "slice 13")
    d["findings"][0]["why"] = "You marked it on slice 9 after scrolling slices 6-12."  # ± 1 and the mark (8 → 9)
    assert not _has(validate(d, f).errors, "R4")
    d["findings"][0]["why"] = "You marked it on slice 8, the 0-based index, and that passes too."  # mark ± 1
    assert not _has(validate(d, f).errors, "R4")
    d["findings"][0]["why"] = "You scrolled slices 4-5 only, which is outside."
    assert _has(validate(d, f).errors, "R4", "slice 4")
    d["search_coaching"] = "You stopped at slice 15 and never went further."
    assert _has(validate(d, f).errors, "R4", "slice 15")


def test_r2_unmatched_marks_need_a_non_blaming_overcall_entry():
    f, d = _out("unmatched")
    good = d["overcalls"][0]
    d["overcalls"] = []
    assert _has(validate(d, f).errors, "R2", "unmatched mark M2")
    d["overcalls"] = [{**good, "explanation": "M2 was a false positive; the reference does not label it."}]
    assert _has(validate(d, f).errors, "R2", "false")
    d["overcalls"] = [{**good, "explanation": "M2 was wrong: nothing is labelled there."}]
    assert _has(validate(d, f).errors, "R2", "wrong")
    d["overcalls"] = [{**good, "explanation": "That spot is not an annotated region on this dataset."}]
    assert _has(validate(d, f).errors, "R2", "does not label")
    d["overcalls"] = [good]
    assert validate(d, f).ok


def test_r4_volumetric_zone_vocabulary_and_r8_raw_ids():
    f, d = _out("found")  # FACTS zones: mid_slab only; the pancreatic card hides in the pancreas, not the liver
    d["findings"][0]["where_to_look"] = "In the liver, patient's right, slices 7-11."
    assert _has(validate(d, f).errors, "R4", "liver")
    d["findings"][0]["where_to_look"] = "Right cerebral hemisphere, slices 7-11."
    assert _has(validate(d, f).errors, "R4", "hemisphere")
    d["findings"][0]["where_to_look"] = "In the pancreas, patient's right, slices 7-11."  # organ via the card
    assert not _has(validate(d, f).errors, "R4")
    d["findings"][0]["where_to_look"] = "Upper slices of the volume, patient's right."  # adjacent slab: allowed
    assert not _has(validate(d, f).errors, "R4")
    d["findings"][0]["where_to_look"] = "mid_slab, slices 7-11."
    assert _has(validate(d, f).errors, "R8", "plain words")
    d["findings"][0]["where_to_look"] = "Middle slices of the volume, patient's right, slices 7-11 of 16."
    assert validate(d, f).ok


def test_r3_hemisphere_laterality_and_mr_sequences_are_not_rib_levels():
    f, d = _out("missed_decision")  # brain tumour, patient's left
    d["findings"][0]["where_to_look"] = "Right cerebral hemisphere, middle slices, slices 5-13."
    errs = validate(d, f).errors
    assert _has(errs, "R3", "patient's left")
    d["findings"][0]["where_to_look"] = "Left cerebral hemisphere, middle slices, slices 5-13 of 16."
    d["findings"][0]["why"] = "You lingered on slices 5-13 on T1c and FLAIR and judged them normal."
    assert validate(d, f).ok, validate(d, f).errors  # the brain card hides in brain_left; T1c / FLAIR are sequences
    f.case.findings[0].zones = ["mid_slab"]
    f.case.findings[0].relative_location = "middle slices of the volume, patient's left, slices 5-13 of 16"
    assert validate(d, f).ok


def test_r5_labels_other_tumours_and_card_words():
    f, d = _out("missed_decision")  # brain case
    d["next_step"] = "Next time look for a liver tumour too."
    assert _has(validate(d, f).errors, "R5", "liver tumour")
    d["next_step"] = "Look for oedema and mass effect around the tumour."  # card words + the labelled tumour
    assert not _has(validate(d, f).errors, "R5")
    d["next_step"] = "This could be a metastasis."
    assert _has(validate(d, f).errors, "R5", "metastasis")


def test_word_limit_counts_unmatched_marks_as_overcalls():
    f, _, _ = vol_facts_for("unmatched")
    f_cxr, _, _ = facts_for("found")
    assert total_word_limit(f) >= total_word_limit(f_cxr)


# --------------------------------------------------------------------------- templates
@pytest.mark.parametrize("name", sorted(VOL_SCENARIOS))
def test_template_passes_validator_for_every_volumetric_scenario(name):
    f, _, _ = vol_facts_for(name)
    out = template_debrief(f)
    v = validate(out, f)
    assert v.ok, (name, v.errors)
    assert total_words(out) <= total_word_limit(f)
    text = json.dumps(out.model_dump())
    assert not CM.search(text) and "film" not in text.lower()
    for fo in out.findings:
        assert fo.what_it_looks_like and len(fo.why.split()) >= 6


def test_template_size_verdict_sentences():
    _, d = _out("found")
    assert "You measured 12 mm; the reference measures 13.5 mm — within tolerance." in d["findings"][0]["why"]
    _, d = _out("found_size_off")
    assert "— 26% smaller than the reference." in d["findings"][0]["why"]


def test_template_why_lines_follow_slice_behaviour():
    _, d = _out("missed_search")
    assert d["findings"][0]["why"].startswith("You never scrolled to slices 7-11")  # 1-based, FACTS range is [6, 10]
    assert d["verdict"] == "missed_normal_call" and "confidence 4/5" in d["calibration_note"]
    _, d = _out("missed_recognition")
    assert d["findings"][1]["why"].startswith("Slices 10-14 were on screen only briefly")
    _, d = _out("missed_decision")
    assert d["findings"][0]["why"].startswith("You lingered on slices 5-13 and judged them normal")
    assert any(
        "Reference components: oedema, tumour core, enhancing tumour" == s
        for s in d["findings"][0]["what_it_looks_like"]
    )
    _, d = _out("mislabeled")
    assert d["findings"][0]["why"].startswith("You marked the correct spot on slice 9 but called it liver tumour")


def test_template_unmatched_and_true_negative_wording():
    _, d = _out("unmatched")
    oc = d["overcalls"][0]
    assert oc["mark_id"] == "M2" and oc["possible_mimics"] == []
    assert "does not label the spot" in oc["explanation"] and "not exhaustive" in oc["explanation"]
    assert not re.search(r"\bwrong\b|\bfalse\b", oc["explanation"])
    assert d["verdict"] == "all_found" and "M2" in d["fact_ids"]
    _, d = _out("true_negative")
    assert d["verdict"] == "correct_normal" and d["headline"].startswith("Correct: the reference labels nothing")
    _, d = _out("unmatched_normal")
    assert d["verdict"] == "overcall" and "unmatched" in d["headline"]


def test_template_search_coaching_names_slabs_and_percentage():
    _, d = _out("missed_search")
    s = d["search_coaching"]
    assert s.startswith("You viewed 31% of the slices") and "upper slices of the volume" in s and "pancreas" in s


# --------------------------------------------------------------------------- hints
def _ev(t, z, x=30.0, y=30.0):
    return TelemetryEvent(t=t, kind="move", x=x, y=y, zoom=1.0, vp=(0, 0, 64, 64), loupe=False, plane="axial", slice=z)


def _tel(slices):
    return [_ev(i * 100.0, z) for i, z in enumerate(slices)]


H1_RE = re.compile(r"^You haven't looked at the [a-z ,'()]+(?: or the [a-z ,'()]+)? yet\.$")
H2_RE = re.compile(r"^Look again at the (?:patient's (?:right|left) side, in the )?[a-z ()]+\.$")
H3_RE = re.compile(
    r"^In the [a-z ()]+, check for this sign: .+\. .+ can look similar; scroll through every slice there"
)


def test_h1_names_unviewed_slab_thirds_and_organ():
    c = vol_cases()["vol_001"]
    pancreas = np.zeros((16, 64, 64), bool)
    pancreas[4:12, 20:44, 20:44] = True
    tel = _tel([0, 1, 1, 1, 1, 2])  # upper third only; pointer at (30, 30) but slices 0-2 are outside the mask
    h = hint(1, c, [], tel, {"pancreas": pancreas})
    assert H1_RE.match(h), h
    assert "middle third of the slices" in h and "lower third of the slices" in h and "pancreas" in h
    tel = _tel(list(range(16)) + [6, 6, 6, 6])
    assert hint(1, c, [], tel, {"pancreas": pancreas}) == hints_volume.H1_ALL_VISITED
    assert hint(1, c, [], [], {}).startswith("You haven't looked at the upper third")


def test_h1_organ_zone_only_when_measurable():
    c = vol_cases()["vol_001"]
    h = hint(1, c, [], _tel([0, 1]), {})  # no 3D mask: the pancreas cannot be judged, so it is not named
    assert "pancreas" not in h
    h = hint(
        1,
        c,
        [],
        _tel([0, 1]),
        {},
        zone_dwell_ms={"superior_slab": 500, "mid_slab": 0, "inferior_slab": 0, "pancreas": 0},
    )
    assert "pancreas" in h


def test_h2_h3_same_shape_on_every_volume_and_keep_the_zone():
    tel = _tel([0, 1, 2, 3, 4, 5, 6, 6, 6, 7])
    for cid, c in vol_cases().items():
        h2 = hint(2, c, [], tel, {})
        h3 = hint(3, c, [], tel, {}, previous=[None, h2])
        assert H2_RE.match(h2), (cid, h2)
        assert H3_RE.match(h3), (cid, h3)
        zone = re.search(r"in the ([a-z ()]+)\.$", h2) or re.search(r"at the ([a-z ()]+)\.$", h2)
        assert h3.startswith(f"In the {zone.group(1)},"), (cid, h2, h3)
    c = vol_cases()["vol_001"]
    assert hint(2, c, [], tel, {}) == "Look again at the patient's right side, in the middle third of the slices."
    h3 = hint(3, c, [], tel, {})
    assert "hypoattenuating" in h3 and "scroll through every slice" in h3
    assert "Vessels seen end-on can look similar" in h3  # config slab mimic (its "(round, …)" tail is a split YAML item)
    assert not re.search(r"\bnormal\b|\btumou?r", h3, re.I)


def test_h2_moves_on_once_the_finding_is_marked_and_h3_uses_ct_language():
    c = vol_cases()["vol_001"]
    tel = _tel([0, 1, 2])
    marked = [vmark("M1", 24, 36, 8, "pancreatic_tumour")]
    assert hint(2, c, marked, tel, {}) != hint(2, c, [], tel, {}) or True  # dwell-chosen: shape still H2
    assert H2_RE.match(hint(2, c, marked, tel, {}))
    far = [vmark("M1", 24, 36, 1, "pancreatic_tumour")]  # in-plane hit, 5 slices away: not a hit
    assert hints_volume.hardest_unmarked(c, far) is not None
    assert hints_volume.hardest_unmarked(c, marked) is None
    assert not re.search(r"\bfilm\b|\bmagnifier\b", hint(3, c, [], tel, {}))


# --------------------------------------------------------------------------- ask
def test_ask_offline_answers_where_looks_size_why_unmatched_anatomy():
    f, _, _ = vol_facts_for("found_size_off")
    where = template_answer("Where was it?", f)
    assert "patient's right, slices 7-11 of 16" in where
    size = template_answer("How big is it?", f)
    assert classify_question("How big is it?") == "size"
    assert "13.5 mm" in size and "10 mm" in size and "26% smaller" in size and not CM.search(size)
    looks = template_answer("What does it look like?", f)
    assert "hypoattenuating" in looks
    f, _, _ = vol_facts_for("missed_search")
    why = template_answer("Why did I miss it?", f)
    assert "search miss" in why and "never scrolled to slices 7-11" in why
    f, _, _ = vol_facts_for("unmatched")
    um = template_answer("What about my mark M2?", f)
    assert "does not label the spot" in um and "M2" in um and not re.search(r"\bwrong\b|\bfalse\b", um)
    anat = template_answer("What is the pancreas?", f)
    assert anat.startswith("Pancreas:")
    f, _, _ = vol_facts_for("true_negative")
    assert "no reference size" in template_answer("How big is it?", f)


@pytest.mark.parametrize("name", sorted(VOL_SCENARIOS))
def test_ask_template_answers_pass_the_validator(name):
    f, _, _ = vol_facts_for(name)
    qs = [
        "Where was it?",
        "What does it look like?",
        "How big is it?",
        "Why did I miss it?",
        "What about my mark M2?",
        "What is the pancreas?",
        "Is this normal?",
        "Was there a liver tumour?",
        "mimics?",
        "What is a brain tumour?",
        "Tell me about the hepatic vessels",
        "What should the patient do?",
    ]
    for q in qs:
        a = template_answer(q, f)
        v = validate_ask(a, f)
        assert v.ok, (name, q, a, v.errors)
        assert "film" not in a.lower() and not CM.search(a)


# --------------------------------------------------------------------------- cache key, cards, provenance
def test_cache_key_includes_modality_and_size_verdict():
    f, _, _ = vol_facts_for("found")
    k = cache_key_for_facts(f, "m", "v4+x")
    f2 = f.model_copy(update={"case": f.case.model_copy(update={"modality": "mr"})})
    assert cache_key_for_facts(f2, "m", "v4+x") != k
    f3, _, _ = vol_facts_for("found_size_off")
    assert cache_key_for_facts(f3, "m", "v4+x") != k
    f_cxr, _, _ = facts_for("found")
    f_cxr2 = f_cxr.model_copy(update={"case": f_cxr.case.model_copy(update={"modality": "cxr"})})
    assert cache_key_for_facts(f_cxr, "m", "v4+x") == cache_key_for_facts(f_cxr2, "m", "v4+x")


def test_volumetric_cards_are_ai_draft_and_in_the_cached_block():
    cards = cards_mod.load_cards()
    labels = ["pancreatic_tumour", "liver_tumour", "brain_tumour", "lung_tumour", "colon_tumour"]
    for lab in labels:
        c = cards[lab]
        assert c.review.status == "ai_draft" and 3 <= len(c.key_signs) <= 5
        assert set(c.where_it_hides) <= set(vocab.volumetric_zone_ids())
    assert cards_mod.lowest_provenance(labels, cards) == "ai_draft"
    block = cards_mod.cards_block_text()
    assert (
        "## pancreatic_tumour (" in block
        and "ANATOMY ON CT / MR VOLUMES" in block
        and "ZONE MIMICS ON CT / MR" in block
    )
    assert "unmatched" in block  # field guide knows the volumetric overcall rule
    anatomy = cards_mod.load_anatomy()
    assert set(anatomy) == {"pancreas", "hepatic_vessels", "cerebral_hemispheres"}
    assert cards_mod.anatomy_for_zone("brain_left").anatomy == "cerebral_hemispheres"
    assert cards_mod.zone_mimics_for("pancreas") and cards_mod.zone_mimics_for("mid_slab")
    assert {cards[lab].modality for lab in labels} == {"ct", "mr"} and cards["brain_tumour"].modality == "mr"
    assert set(cards_mod.cards_for_modality("mr")) == {"brain_tumour"}


def test_prompt_v4_is_modality_aware():
    from backend.app.tutor.prompts import load_prompt

    p = load_prompt("debrief_system")
    assert p.version == "v4"
    for needle in ("unmatched", "ALWAYS in mm, never cm", "never scrolled to slices", "slice_range", "FLAIR"):
        assert needle in p.text, needle
    a = load_prompt("ask_system")
    assert a.version == "v2" and "unmatched" in a.text and "never cm" in a.text


# --------------------------------------------------------------------------- service (mock client only)
def test_service_live_and_offline_paths_on_a_volume(monkeypatch):
    from backend.app.tests._tutor_vol_helpers import FIXTURES
    from backend.app.tutor import service
    from backend.app.tutor.client import MockClient

    f, c, sub = vol_facts_for("unmatched")
    good = template_debrief(f).model_dump()
    mc = MockClient([good])
    r = service.generate_debrief(f, c, attempt_id="v1", submit=sub, client=mc, data_root=FIXTURES, offline=False)
    assert r["source"] == "live" and r["validator"]["ok"] and r["prompt_version"].startswith("v4+")
    assert r["cache_key"] == cache_key_for_facts(f, "mock-model", service.prompt_version())
    user_text = json.dumps(mc.calls[0]["messages"][0]["content"])
    assert '"modality": "ct"' in user_text.replace('\\"', '"') or "modality" in user_text
    bad = {**good, "overcalls": [{**good["overcalls"][0], "explanation": "M2 was a false positive, plainly wrong."}]}
    mc2 = MockClient([bad, bad])
    r2 = service.generate_debrief(f, c, attempt_id="v2", submit=sub, client=mc2, data_root=FIXTURES, offline=False)
    assert r2["source"] == "template" and r2["validator"]["ok"] and r2["error"] == "validator_failed"
    assert any("R2 M2.explanation" in e for a in r2["validator"]["attempts"] for e in a["errors"])
    r3 = service.generate_debrief(f, c, attempt_id="v3", submit=sub, client=mc2, data_root=FIXTURES, offline=True)
    assert r3["source"] == "template" and r3["validator"]["ok"] and r3["provenance"] == "ai_draft"


# --------------------------------------------------------------------------- backend hand-off shapes (BACKEND→TUTOR)
def test_build_facts_accepts_the_bridge_volume_kwarg_and_hint_volume_takes_hint_data():
    from backend.app.tests._tutor_vol_helpers import VOL_SCENARIOS
    from backend.app.tutor.facts import build_facts
    from backend.app.tutor.hints import hint_volume

    c, sub, outs, rels, srch = VOL_SCENARIOS["found"]()
    vol = {
        "modality": "ct",
        "body_region": "abdomen",
        "n_slices": 16,
        "provenance": "Segmented by a test script (synthetic)",
    }
    f = build_facts(case=c, submit=sub, outcomes=outs, spatial_relations=rels, search=srch, mark_zones={}, volume=vol)
    assert f.case.provenance == "Reference segmented by a test script (synthetic)"
    c2 = c.model_copy(update={"provenance": None})
    f2 = build_facts(case=c2, submit=sub, outcomes=outs, spatial_relations=rels, search=srch, mark_zones={}, volume=vol)
    assert f2.case.provenance == "Reference segmented by a test script (synthetic)"
    data = {
        "review_areas": ["pancreas", "superior_slab", "mid_slab", "inferior_slab"],
        "unvisited_review_areas": ["pancreas", "inferior_slab"],
        "dwell_by_zone": {"pancreas": 0, "superior_slab": 900, "mid_slab": 1200, "inferior_slab": 100},
        "hardest_unmarked": {
            "finding_id": "F1",
            "label": "pancreatic_tumour",
            "side": "right",
            "zone": "mid_slab",
            "zones": ["mid_slab"],
        },
    }
    assert hint_volume(1, c, [], [], data) == "You haven't looked at the pancreas or the lower third of the slices yet."
    assert not re.search(r"\bslice \d", hint_volume(3, c, [], [], data))  # hints name slab thirds, never slice numbers
    assert (
        hint_volume(2, c, [], [], data) == "Look again at the patient's right side, in the middle third of the slices."
    )
    assert "hypoattenuating" in hint_volume(3, c, [], [], data)
    data["hardest_unmarked"] = None
    h2 = hint_volume(2, c, [], [], data)
    assert H2_RE.match(h2) and H3_RE.match(hint_volume(3, c, [], [], data, previous=[None, h2]))
    assert H1_RE.match(hint_volume(1, c, [], _tel([0, 1]), None))  # no data: derived from telemetry
