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


def test_very_crowded_film_uses_tiny_level_within_scaled_limit():
    """30 findings (real ChestX-Det films reach 36): every finding listed, R7 allowance applies above 8."""
    from backend.app.tutor.validator import total_word_limit

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
    assert len(out.findings) == 30 and total_word_limit(f) == 160 + 6 * 22
    assert {x.why for x in out.findings} <= {
        "Found it.",
        "Found it, named it wrong.",
        "Never looked there.",
        "Looked past it.",
        "Looked, judged it normal.",
    }
