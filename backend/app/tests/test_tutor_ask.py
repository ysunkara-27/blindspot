"""Ask the tutor (SPEC §8.9): validated live answers, template fallback, no management advice."""

import anthropic
import pytest

from backend.app.tests._tutor_helpers import SCENARIOS, facts_for
from backend.app.tutor.ask import (
    OFFLINE_HELP,
    REFUSE_MANAGEMENT,
    answer_question,
    ask,
    classify_question,
    template_answer,
)
from backend.app.tutor.cards import load_cards, load_zone_mimics
from backend.app.tutor.client import LiveCallError, MockClient
from backend.app.tutor.validator import validate_ask, words


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("unit tests must never construct a real Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)


QUESTIONS = [
    "Why did I miss it?",
    "What does a pneumothorax look like?",
    "Is this pneumonia?",
    "How should we treat this patient?",
    "Where exactly was it?",
    "Was there an effusion too?",
    "What is a mimic?",
    "Why was my mark wrong?",
    "What is a nodule?",
    "What is a mass?",
    "How do I recognise it?",
    "Was it normal?",
    "Where was F2?",
    "What did I miss?",
    "Tell me a joke",
]
CORE = ["Where was it?", "What does it look like?", "Why did I miss it?", "What is a nodule?", "What is a mimic?"]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_template_answers_pass_validator(name):
    f, _, _ = facts_for(name)
    for q in QUESTIONS:
        a = template_answer(q, f)
        assert validate_ask(a, f).ok, (q, a, validate_ask(a, f).errors)
        assert 0 < words(a) <= 90, (q, a)
        assert template_answer(q, f) == a  # deterministic


# --------------------------------------------------------------------------- question-aware offline answers (QA #12)
@pytest.mark.parametrize(
    ("q", "intent"),
    [
        ("Where exactly was it?", "where"),
        ("Which side was it on?", "where"),
        ("What did I miss?", "where"),
        ("What does a pneumothorax look like?", "looks"),
        ("How do I recognise consolidation?", "looks"),
        ("Why did I miss it?", "why_missed"),
        ("Why didn't I see the nodule?", "why_missed"),
        ("What is a nodule?", "define"),
        ("What is a mimic?", "mimic"),
        ("Why was my mark wrong?", "mimic"),
        ("What could M1 have been?", "mimic"),
        ("Was it normal?", "normal"),
        ("How should we treat this patient?", "management"),
        ("Tell me a joke", "other"),
    ],
)
def test_classify_question(q, intent):
    assert classify_question(q) == intent


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_different_questions_get_different_answers(name):
    f, _, _ = facts_for(name)
    answers = [template_answer(q, f) for q in CORE]
    assert len(set(answers)) == len(CORE), answers


def test_where_gives_relative_location_of_named_or_first_missed_finding():
    f, _, _ = facts_for("multi")  # F1 mass found, F2 nodule missed_search
    loc = {x.id: x.relative_location for x in f.case.findings}
    assert template_answer("Where was it?", f).startswith(f"F2 (nodule) is in the {loc['F2']}")
    assert template_answer("Where was F1?", f).startswith(f"F1 (mass) is in the {loc['F1']}")
    assert template_answer("Where was the mass?", f).startswith(f"F1 (mass) is in the {loc['F1']}")
    a = template_answer("Where was F7?", f)
    assert a.startswith("This film has F1 and F2; there is no F7.")
    sr = template_answer("Where was it?", facts_for("missed_search")[0])
    assert "your mark was in the right upper zone" in sr  # code-built spatial relation is reused
    tn = template_answer("Where was it?", facts_for("true_negative")[0])
    assert tn == "Radiologists marked nothing on this film, so there is no finding to locate."


def test_looks_uses_the_cards_key_signs():
    f, _, _ = facts_for("found")
    sign = load_cards()["nodule"].key_signs[0]
    a = template_answer("What does it look like?", f)
    assert a.startswith("Signs of a nodule: ") and sign[1:].rstrip(".") in a
    b = template_answer("How do I recognise it?", facts_for("missed_search")[0])
    assert b.startswith("Signs of a pneumothorax: ")


@pytest.mark.parametrize(
    ("name", "expect"),
    [
        ("missed_search", ["F1 (pneumothorax) was a search miss.", "never paused in the left upper zone"]),
        ("missed_recognition", ["was a recognition miss.", "only briefly"]),
        ("missed_decision", ["was a decision miss.", "judged it normal", "look-alike"]),
        ("mislabeled", ["You marked the correct spot but called it mass."]),
        ("pattern_missed", ["You did not tick cardiomegaly in Global findings."]),
        ("multi", ["F2 (nodule) was a search miss."]),
        ("found", ["You did not miss anything radiologists marked"]),
        ("true_negative", ["Radiologists marked nothing on this film, so there was nothing to miss."]),
    ],
)
def test_why_missed_explains_the_miss_type_from_outcomes(name, expect):
    a = template_answer("Why did I miss it?", facts_for(name)[0])
    for e in expect:
        assert e in a, (e, a)


def test_define_uses_the_cards_one_liner():
    cards = load_cards()
    a = template_answer("What is a nodule?", facts_for("found")[0])
    assert a.startswith("Nodule: ") and cards["nodule"].one_liner[1:].rstrip(".") in a
    m = template_answer("What is a mass?", facts_for("mislabeled")[0])  # the learner's own label may be explained
    assert "Mass: " in m and m.startswith("Radiologists did not mark that on this film; they marked nodule.")
    n = template_answer("What is a pneumothorax?", facts_for("true_negative")[0])
    assert "pneumothorax" not in n.lower()  # never names a label that is not part of this case


def test_mimic_questions_use_zone_mimics_for_overcalls():
    f, _, _ = facts_for("false_positive_normal")
    zone = next(o.zone for o in f.outcomes if o.result == "false_positive")
    first = load_zone_mimics()["entries"][zone][0]
    a = template_answer("What is a mimic?", f)
    assert a.startswith("Radiologists marked nothing where you placed M1") and first[1:] in a
    found = template_answer("What is a mimic?", facts_for("found")[0])  # no overcall: the card's mimics
    assert found.startswith("A mimic is a normal structure") and "nipple shadow" in found.lower()
    assert template_answer("Why was my mark wrong?", facts_for("found")[0]).startswith("M1 was on F1 (nodule)")
    assert "labelled it mass" in template_answer("Why was my mark wrong?", facts_for("mislabeled")[0])
    none = template_answer("Why was my mark wrong?", facts_for("true_negative")[0])
    assert none == "You did not place any marks on this film."
    pf = template_answer("What is a mimic?", facts_for("pattern_false_normal")[0])
    assert pf.startswith("You ticked emphysema, but radiologists did not mark it")


def test_normal_question_and_fallback_line():
    assert template_answer("Was it normal?", facts_for("true_negative")[0]).startswith("Yes: radiologists marked")
    assert template_answer("Was it normal?", facts_for("found")[0]).startswith("No: radiologists marked nodule.")
    for name in SCENARIOS:
        assert template_answer("Tell me a joke", facts_for(name)[0]) == OFFLINE_HELP
    assert words(OFFLINE_HELP) <= 90


def test_ask_result_carries_an_error_code_for_template_answers():
    f, c, _ = facts_for("found")
    assert ask("Where was it?", f, c, previous=[], offline=True)["error"] == "offline"
    live = ask("q", f, c, previous=[], offline=False, client=MockClient([{"answer": "F1 is a nodule."}]))
    assert live["source"] == "live" and live["error"] is None
    t = ask("q", f, c, previous=[], offline=False, client=MockClient([LiveCallError("timeout")]))
    assert t["error"] == "timeout"
    v = ask("q", f, c, previous=[], offline=False, client=MockClient([{"answer": "This could be pneumonia."}]))
    assert v["error"] == "validator_failed"


def test_rib_words_inside_a_zone_mimic_are_not_a_location_but_invented_rib_levels_are():
    f, _, _ = facts_for("missed_search")
    ok = "Normal structures there: overlap of the first rib and the clavicle; costal cartilage of the first rib."
    assert validate_ask(ok, f).ok, validate_ask(ok, f).errors
    bad = validate_ask("The pneumothorax reaches the fourth rib.", f)
    assert not bad.ok and any(e.startswith("R4") for e in bad.errors)


def test_management_question_is_redirected():
    f, _, _ = facts_for("found")
    assert template_answer("What antibiotic should I give?", f) == REFUSE_MANAGEMENT


def test_question_about_unmarked_label_does_not_name_it():
    f, _, _ = facts_for("found")
    a = template_answer("Is there a pneumothorax?", f)
    assert a.startswith("Radiologists did not mark that on this film; they marked nodule.")
    assert "pneumothorax" not in a.lower()


def test_offline_uses_template():
    f, c, _ = facts_for("missed_search")
    mc = MockClient([{"answer": "x"}])
    r = ask("Why did I miss it?", f, c, previous=[], offline=True, client=mc)
    assert r["source"] == "template" and r["validator"]["ok"] and mc.calls == []


def test_live_answer_ok_and_request_shape():
    f, c, _ = facts_for("found")
    ans = "F1 is a nodule in the right mid zone. Vessels branch and taper; a nodule is a round spot."
    mc = MockClient([{"answer": ans}])
    r = ask("Why is it a nodule?", f, c, previous=[{"question": "q0", "answer": "a0"}], offline=False, client=mc)
    assert r["source"] == "live" and r["answer"] == ans
    call = mc.calls[0]
    assert call["system"][0]["text"].startswith("You are the tutor in Blindspot")
    assert call["system"][1]["cache_control"] == {"type": "ephemeral"}
    text = call["messages"][0]["content"][-1]["text"]
    assert "EARLIER QUESTION: q0" in text and text.rstrip().endswith("QUESTION: Why is it a nodule?")
    assert call["schema"]["required"] == ["answer"]


@pytest.mark.parametrize(
    "bad",
    [
        "This could be pneumonia.",
        "The nodule is in the left lung.",
        "You should treat it.",
        " ".join(["word"] * 95),
    ],
)
def test_invalid_live_answer_falls_back(bad):
    f, c, _ = facts_for("found")
    r = ask("q", f, c, previous=[], offline=False, client=MockClient([{"answer": bad}]))
    assert r["source"] == "template" and r["validator"]["fallback_reason"] == "validator_failed"
    assert r["validator"]["live_errors"]


def test_api_error_and_bad_json_fall_back():
    f, c, _ = facts_for("found")
    r = ask("q", f, c, previous=[], offline=False, client=MockClient([LiveCallError("timeout")]))
    assert r["validator"]["fallback_reason"] == "live_timeout"
    r = ask("q", f, c, previous=[], offline=False, client=MockClient(["not json"]))
    assert r["validator"]["fallback_reason"] == "bad_json"


def test_answer_question_returns_api_model():
    f, c, _ = facts_for("true_negative")
    resp = answer_question("Was it normal?", f, c, remaining=2, offline=True)
    assert resp.remaining == 2 and resp.source == "template" and resp.answer
