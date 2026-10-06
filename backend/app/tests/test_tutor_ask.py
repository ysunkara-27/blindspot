"""Ask the tutor (SPEC §8.9): validated live answers, template fallback, no management advice."""

import anthropic
import pytest

from backend.app.tests._tutor_helpers import SCENARIOS, facts_for
from backend.app.tutor.ask import REFUSE_MANAGEMENT, answer_question, ask, template_answer
from backend.app.tutor.client import LiveCallError, MockClient
from backend.app.tutor.validator import validate_ask


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
]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_template_answers_pass_validator(name):
    f, _, _ = facts_for(name)
    for q in QUESTIONS:
        a = template_answer(q, f)
        assert validate_ask(a, f).ok, (q, a, validate_ask(a, f).errors)


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
