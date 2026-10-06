"""Validator (SPEC §8.6): seed each kind of error into an otherwise valid debrief and prove it is caught."""

import pytest

from backend.app.tests._tutor_helpers import facts_for
from backend.app.tutor.templates import template_debrief
from backend.app.tutor.validator import allowed_verdicts, side_words, validate, validate_ask, zone_mentions
from shared.contracts import DebriefFindingOut, DebriefOutput, DebriefOvercall


def base(name="found"):
    f, _, _ = facts_for(name)
    out = template_debrief(f)
    assert validate(out, f).ok, validate(out, f).errors
    return f, out.model_dump()


def errs(d, f):
    return validate(DebriefOutput.model_validate(d), f).errors


def has(errors, tag, text=""):
    return any(e.startswith(tag) and text.lower() in e.lower() for e in errors)


# ----------------------------------------------------------------------------- R1 / R2 structure
def test_r1_extra_missing_duplicate_and_wrong_result():
    f, d = base("found")
    extra = dict(d, findings=d["findings"] + [dict(d["findings"][0], finding_id="F9")])
    assert has(errs(extra, f), "R1", "F9 is not in FACTS")
    assert has(errs(dict(d, findings=[]), f), "R1", "F1 is missing")
    dup = dict(d, findings=d["findings"] * 2)
    assert has(errs(dup, f), "R1", "appears 2 times")
    wrong = dict(d, findings=[dict(d["findings"][0], result="missed_search")])
    assert has(errs(wrong, f), "R1", "FACTS says 'found'")


def test_r2_overcalls_must_equal_false_positive_marks():
    f, d = base("missed_search")
    assert has(errs(dict(d, overcalls=[]), f), "R2", "M1 needs an overcall")
    bogus = dict(d, overcalls=d["overcalls"] + [dict(d["overcalls"][0], mark_id="M7")])
    assert has(errs(bogus, f), "R2", "M7 is not a false-positive")
    f2, d2 = base("found")  # M1 is a true positive there
    tp = dict(d2, overcalls=[{"mark_id": "M1", "explanation": "Nothing there.", "possible_mimics": []}])
    assert has(errs(tp, f2), "R2", "M1 is not a false-positive")


# ----------------------------------------------------------------------------- R3 laterality
def test_r3_wrong_side_word_in_where_to_look():
    f, d = base("found")  # nodule on the patient's RIGHT
    d["findings"][0]["where_to_look"] = "Left mid zone."
    e = errs(d, f)
    assert has(e, "R3", "patient's right"), e


def test_r3_image_relative_phrasing_is_ignored():
    f, d = base("found")
    d["findings"][0]["where_to_look"] = "Right mid zone; remember the patient's right appears on the left of the image."
    assert errs(d, f) == []
    assert side_words("on the left side of the image, the patient's right lung") == {"right"}


def test_r3_bilateral_allows_both_sides():
    f, d = base("bilateral")
    f.case.findings[1].side = "bilateral"
    d["findings"][1]["where_to_look"] = "Left lower zone, compared with the right lower zone."
    assert not has(errs(d, f), "R3")


def test_r3_sentence_level_laterality_outside_where_to_look():
    f, d = base("found")
    d["findings"][0]["why"] = "The nodule sits in the left lung."
    assert has(errs(d, f), "R3", "'left' about the nodule")
    d["findings"][0]["why"] = "Your mark M1 was in the left lung; the nodule is in the right mid zone."
    assert not has(errs(d, f), "R3")


# ----------------------------------------------------------------------------- R4 zone vocabulary
def test_r4_zone_term_not_in_finding_zones_or_neighbours():
    f, d = base("found")  # zones: right_mid_zone only
    d["findings"][0]["where_to_look"] = "Right apex, near the clavicle."
    assert has(errs(d, f), "R4", "right apex")
    d["findings"][0]["where_to_look"] = "Just above the costophrenic angle."
    assert has(errs(d, f), "R4", "costophrenic")
    d["findings"][0]["where_to_look"] = "Right mid zone, next to the right hilum."  # hilum is a neighbour
    assert not has(errs(d, f), "R4")


def test_r4_no_lobes_or_rib_levels():
    f, d = base("found")
    d["findings"][0]["where_to_look"] = "Right lower lobe, behind the sixth rib."
    e = errs(d, f)
    assert has(e, "R4", "lobe") and has(e, "R4", "rib level")
    f2, d2 = base("found")
    d2["search_coaching"] = "Check the upper lobes on every film."
    assert has(errs(d2, f2), "R4", "lobe")


def test_r4_relative_location_terms_always_allowed():
    f, d = base("found")
    f.case.findings[0].relative_location = "right mid zone, lateral third, just below the right hilum"
    d["findings"][0]["where_to_look"] = "Right mid zone, lateral third, just below the right hilum."
    assert errs(d, f) == []
    assert zone_mentions("right lower zone, just above the right costophrenic angle") == (
        ["right_lower_zone", "right_costophrenic_angle"],
        [],
    )


# ----------------------------------------------------------------------------- R5 hallucinated labels
def test_r5_hallucinated_non_taxonomy_finding():
    f, d = base("found")
    d["findings"][0]["why"] = "This could also be pneumonia."
    assert has(errs(d, f), "R5", "pneumonia")


def test_r5_taxonomy_label_not_in_facts():
    f, d = base("found")  # nodule case; learner said nodule
    d["search_coaching"] = "Also look for a pneumothorax at the apices."
    assert has(errs(d, f), "R5", "pneumothorax")


def test_r5_related_learner_and_card_mimic_terms_are_allowed():
    f, d = base("found")
    d["findings"][0]["why"] = "A nodule is smaller than a mass; a calcification is as white as bone."
    assert not has(errs(d, f), "R5")
    f2, d2 = base("missed_search")  # pneumothorax card mimic mentions a bulla in emphysema
    d2["findings"][0]["what_it_looks_like"] = ["Not a large bulla in emphysema: the line parallels the chest wall"]
    assert not has(errs(d2, f2), "R5")
    f3, d3 = base("mislabeled")  # learner chose mass
    d3["findings"][0]["why"] = "You called it a mass; this is a nodule."
    assert not has(errs(d3, f3), "R5")


def test_r5_normal_case_allows_only_learner_labels():
    f, d = base("false_positive_normal")  # learner marked a nodule on a normal film
    d["overcalls"][0]["explanation"] = "Radiologists marked nothing there; it is not a nodule or an effusion."
    e = errs(d, f)
    assert has(e, "R5", "effusion") and not has(e, "R5", "nodule")


# ----------------------------------------------------------------------------- R6 banned content
@pytest.mark.parametrize(
    "text,needle",
    [
        ("A chest tube would fix this.", "chest tube"),
        ("We would treat this with antibiotics.", "treat"),
        ("Order a follow-up CT.", "follow-up ct"),
        ("The nodule measures 3 cm.", "3 cm"),
        ("It is about 12mm across.", "12mm"),
        ("This patient has a serious problem.", "this patient has"),
        ("The prognosis is good.", "prognosis"),
        ("This is urgent.", "urgent"),
    ],
)
def test_r6_banned_content(text, needle):
    f, d = base("found")
    d["next_step"] = text
    assert has(errs(d, f), "R6", needle)


def test_r6_measurements_allowed_when_pixel_spacing_known():
    f, d = base("found")
    d["next_step"] = "The nodule is about 8 mm across."
    assert has(errs(d, f), "R6", "8 mm")
    f.case.pixel_spacing_mm = 0.14
    assert not has(errs(d, f), "R6")


# ----------------------------------------------------------------------------- R7 lengths
def test_r7_headline_and_total_length():
    f, d = base("found")
    d["headline"] = " ".join(["word"] * 20)
    assert has(errs(d, f), "R7", "headline has 20 words")
    f2, d2 = base("found")
    d2["search_coaching"] = " ".join(["look"] * 170)
    assert has(errs(d2, f2), "R7", "maximum 160")


# ----------------------------------------------------------------------------- R8 consistency
def test_r8_verdict_fact_ids_and_raw_zone_ids():
    f, d = base("found")
    assert has(errs(dict(d, verdict="missed"), f), "R8", "use all_found")
    assert has(errs(dict(d, fact_ids=["F1", "F4"]), f), "R8", "F4")
    d["findings"][0]["where_to_look"] = "right_mid_zone"
    assert has(errs(d, f), "R8", "plain words")


def test_allowed_verdicts_per_scenario():
    expect = {
        "found": {"all_found"},
        "multi": {"partly_found"},
        "missed_decision": {"missed"},
        "missed_recognition": {"missed_normal_call", "missed"},
        "true_negative": {"correct_normal"},
        "false_positive_normal": {"overcall", "missed_normal_call"},
        "pattern_found": {"all_found"},
    }
    for name, v in expect.items():
        assert allowed_verdicts(facts_for(name)[0]) == v, name


def test_schema_violation_is_reported_not_raised():
    f, d = base("found")
    r = validate({"headline": "x"}, f)
    assert not r.ok and r.errors[0].startswith("R0")


def test_hand_written_valid_debrief_passes():
    f, _, _ = facts_for("missed_search")
    out = DebriefOutput(
        headline="You missed a small pneumothorax at the top of the left lung.",
        verdict="missed",
        findings=[
            DebriefFindingOut(
                finding_id="F1",
                result="missed_search",
                where_to_look="Left upper zone, toward the left apex.",
                what_it_looks_like=["A thin white pleural line with no lung markings beyond it"],
                why="Your search never reached the left upper zone, so the pleural line was never in view.",
            )
        ],
        overcalls=[
            DebriefOvercall(
                mark_id="M1",
                explanation="Radiologists marked nothing at M1 in the right apex.",
                possible_mimics=["Overlap of the first rib and the clavicle"],
            )
        ],
        search_coaching="Check both apices with the loupe on every film.",
        calibration_note="You were confident (4/5) in M1, which was not a finding.",
        next_step="Trace the lung edge at both apices before you submit.",
        fact_ids=["F1", "M1"],
    )
    assert validate(out, f).ok, validate(out, f).errors


# ----------------------------------------------------------------------------- ask answers
def test_validate_ask_catches_side_label_banned_and_length():
    f, _, _ = facts_for("found")  # right mid zone nodule
    ok = "F1 is a nodule in the right mid zone: a small round white spot. Vessels branch; nodules do not."
    assert validate_ask(ok, f).ok, validate_ask(ok, f).errors
    assert not validate_ask("The nodule is in the left lung.", f).ok
    assert not validate_ask("It is in the left lower zone.", f).ok
    assert not validate_ask("It might be pneumonia.", f).ok
    assert not validate_ask("You would treat it with antibiotics.", f).ok
    assert not validate_ask(" ".join(["word"] * 91), f).ok
    assert validate_ask("The patient's right appears on the left of the image.", f).ok
