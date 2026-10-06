"""Offline templates (SPEC §8.7): every result type has a validator-passing template."""

import pytest

from backend.app.tests._tutor_helpers import SCENARIOS, cases, facts_for
from backend.app.tutor.facts import facts_finding
from backend.app.tutor.templates import _total_words, template_debrief
from backend.app.tutor.validator import validate
from shared.contracts import FactsMark, Finding, Outcome

ALL_RESULTS = {
    "found",
    "mislabeled",
    "missed_search",
    "missed_recognition",
    "missed_decision",
    "pattern_found",
    "pattern_missed",
    "false_positive",
    "true_negative",
    "pattern_false",
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_template_passes_validator(name):
    f, _, _ = facts_for(name)
    out = template_debrief(f)
    v = validate(out, f)
    assert v.ok, v.errors
    assert {x.finding_id for x in out.findings} == {x.id for x in f.case.findings}
    assert _total_words(out) <= 160


def test_scenarios_cover_every_result_type():
    seen = {o.result for name in SCENARIOS for o in facts_for(name)[0].outcomes}
    assert ALL_RESULTS <= seen


def test_templates_are_deterministic():
    for name in SCENARIOS:
        a = template_debrief(facts_for(name)[0]).model_dump_json()
        b = template_debrief(facts_for(name)[0]).model_dump_json()
        assert a == b


def test_missed_search_template_follows_spec_wording():
    f, _, _ = facts_for("missed_search")
    out = template_debrief(f)
    fo = out.findings[0]
    assert fo.where_to_look.lower().startswith("left upper zone")
    assert fo.why.startswith("Your search never paused in the left upper zone.")
    assert len(fo.what_it_looks_like) == 2
    assert out.overcalls[0].mark_id == "M1" and out.overcalls[0].possible_mimics
    assert out.calibration_note.startswith("You rated M1 4/5")


def test_crowded_case_shortens_until_it_fits():
    """Six findings + three false positives still produce a valid, ≤ 160-word template."""
    f, case, _ = facts_for("multi")
    src: Finding = cases()["syn_005"].findings[1]
    extra = []
    for i in range(3, 7):
        g = src.model_copy(update={"finding_id": f"syn_005#F{i}"})
        extra.append(facts_finding(g, case))
    f.case.findings.extend(extra)
    f.outcomes.extend(Outcome(target=x.id, result="missed_recognition", dwell_ms=400.0) for x in extra)
    for j in (2, 3, 4):
        f.learner.marks.append(FactsMark(id=f"M{j}", label="nodule", confidence=3, zone="right_mid_zone"))
        f.outcomes.append(Outcome(target=f"M{j}", result="false_positive", zone="right_mid_zone"))
    out = template_debrief(f)
    v = validate(out, f)
    assert v.ok, v.errors
    assert len(out.findings) == 6 and len(out.overcalls) == 3


def test_headline_counts_localized_findings_like_the_facts_card():
    """found + mislabeled + pattern_found count as found (backend/app/facts_card.py convention)."""
    f, _, _ = facts_for("mislabeled")
    assert template_debrief(f).headline == "You found it, but the label needs another look."
    f2, _, _ = facts_for("multi")  # F1 found, F2 missed
    assert template_debrief(f2).headline.startswith("You found 1 of 2 findings")
    f2.outcomes[0] = f2.outcomes[0].model_copy(update={"result": "mislabeled", "learner_label": "nodule"})
    assert template_debrief(f2).headline.startswith("You found 1 of 2 findings")


def test_very_crowded_film_lists_every_finding_within_the_scaled_limit():
    """30 findings (real ChestX-Det films reach 36): every finding listed with a sign and a full sentence (R9); the
    R7 limit grows with the mandatory content (50 + 28 per finding + 14 per false-positive mark)."""
    from backend.app.tutor.cards import load_cards, load_zone_mimics
    from backend.app.tutor.templates import _build
    from backend.app.tutor.validator import total_word_limit, words

    f, case, _ = facts_for("multi")
    src: Finding = cases()["syn_005"].findings[1]
    results = ["found", "mislabeled", "missed_search", "missed_recognition", "missed_decision"]
    for i in range(3, 31):
        x = facts_finding(src.model_copy(update={"finding_id": f"syn_005#F{i}"}), case)
        f.case.findings.append(x)
        r = results[i % 5]
        f.outcomes.append(Outcome(target=x.id, result=r, learner_label="mass" if r == "mislabeled" else None))
    out = template_debrief(f)
    v = validate(out, f)
    assert v.ok, v.errors
    assert len(out.findings) == 30 and total_word_limit(f) == 50 + 28 * 30
    assert _total_words(out) <= total_word_limit(f)
    assert all(len(x.what_it_looks_like) >= 1 and words(x.why) >= 6 for x in out.findings)
    # the most compact level ("tiny") is still made of full sentences, never chips
    tiny = _build(f, load_cards(), load_zone_mimics(), "tiny")
    assert validate(tiny, f).ok, validate(tiny, f).errors
    assert {x.why for x in tiny.findings} <= {
        "You marked it and named it correctly.",
        "You marked the correct spot but called it mass.",
        "Your search never paused on this area.",
        "Your cursor crossed this area only briefly.",
        "You looked here a while and judged it normal.",
    }
    assert all(len(x.what_it_looks_like) == 1 and x.what_it_looks_like[0] for x in tiny.findings)
    assert _total_words(tiny) < _total_words(out)


# --------------------------------------------------------------------------- pattern locations (syn_007)
def _with_pattern_location(name: str, rel: str, side: str, zones: list[str], primary: str):
    f, _, _ = facts_for(name)
    ff = f.case.findings[0].model_copy(
        update={"relative_location": rel, "side": side, "zones": zones, "primary_zone": primary}
    )
    case = f.case.model_copy(update={"findings": [ff]})
    return f.model_copy(update={"case": case})


@pytest.mark.parametrize("name", ["pattern_found", "pattern_missed"])
def test_pattern_templates_use_relative_location(name):
    f, _, _ = facts_for(name)  # syn_007: cardiomegaly, relative_location "cardiac silhouette", ctr 0.62
    out = template_debrief(f)
    where = out.findings[0].where_to_look
    assert where.startswith("Cardiac silhouette") and "CTR 0.62" in where and "heart width" in where
    assert validate(out, f).ok, validate(out, f).errors


@pytest.mark.parametrize(
    ("rel", "side", "zones", "primary"),
    [
        (
            "cardiac silhouette, enlarged (CTR 0.62, measured automatically)",
            "midline",
            ["cardiac_silhouette", "retrocardiac", "left_lower_zone"],
            "cardiac_silhouette",
        ),
        (
            "both lungs, mainly the upper zones",
            "bilateral",
            ["right_upper_zone", "left_upper_zone", "right_apex", "left_apex"],
            "right_upper_zone",
        ),
        (
            "left lung, mainly the upper zone, including the apex, overlapping the left clavicle",
            "left",
            ["left_upper_zone", "left_apex"],
            "left_upper_zone",
        ),
    ],
)
def test_validator_accepts_pattern_location_wording_and_templates_copy_it(rel, side, zones, primary):
    f = _with_pattern_location("pattern_missed", rel, side, zones, primary)
    out = template_debrief(f)
    where = out.findings[0].where_to_look
    assert where.lower().startswith(rel.split(" (")[0].split(",")[0].lower()), where
    assert where.count("CTR") <= 1  # no duplicated ratio when the location already carries it
    v = validate(out, f)
    assert v.ok, v.errors
    # the same wording, verbatim, is accepted in a live-style where_to_look; a zone FACTS lacks is still caught
    ok = out.model_copy(update={"findings": [out.findings[0].model_copy(update={"where_to_look": rel + "."})]})
    assert validate(ok, f).ok, validate(ok, f).errors
    bad_where = "Right costophrenic angle." if side != "right" else "Left costophrenic angle."
    bad = out.model_copy(update={"findings": [out.findings[0].model_copy(update={"where_to_look": bad_where})]})
    assert not validate(bad, f).ok
