"""Round 3 debrief quality (UX audit: empty "what it looks like", stubs such as "Never examined." / "Pattern missed."
on crowded films and normal calls) and the drill focus line. Mock client only — never the network."""

from __future__ import annotations

import json

import anthropic
import pytest

from backend.app.tests._tutor_helpers import SCENARIOS, cases, facts_for, fixture_root
from backend.app.tutor import service
from backend.app.tutor.cache import cache_key_for_facts
from backend.app.tutor.cards import cards_block_text, load_cards, load_zone_mimics
from backend.app.tutor.client import MockClient
from backend.app.tutor.facts import facts_finding, facts_json
from backend.app.tutor.prompts import load_prompt
from backend.app.tutor.templates import LEVELS, _build, template_debrief
from backend.app.tutor.validator import WHY_MIN_WORDS, total_word_limit, total_words, validate, words
from shared.contracts import DebriefOutput, FactsMark, Finding, Outcome

STUBS = {"Never examined.", "Pattern missed.", "Never looked there.", "Looked past it.", "Not ticked.", "Found it."}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("unit tests must never construct a real Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)


def _complete(out: DebriefOutput) -> None:
    for x in out.findings:
        assert x.what_it_looks_like and all(s.strip() for s in x.what_it_looks_like), x.finding_id
        assert 1 <= len(x.what_it_looks_like) <= 2
        assert words(x.why) >= WHY_MIN_WORDS, (x.finding_id, x.why)
        assert x.why not in STUBS and x.why.rstrip().endswith((".", "!", "?"))


def _crowded(n: int, declared_normal: bool = False, n_fp: int = 0):
    """syn_005 blown up to n findings with every miss type (synthetic; never shown in the UI)."""
    f, case, sub = facts_for("multi")
    src: Finding = cases()["syn_005"].findings[1]
    results = ["missed_search", "missed_recognition", "missed_decision"]
    if not declared_normal:
        results += ["found", "mislabeled"]
    f.outcomes[:] = [o for o in f.outcomes if o.target.startswith("F")]
    f.learner.marks.clear()
    if declared_normal:
        f.learner.declared_normal = True
        f.learner.normal_confidence = 4
        f.outcomes[0] = f.outcomes[0].model_copy(update={"result": "missed_decision", "matched": None})
    for i in range(3, n + 1):
        x = facts_finding(src.model_copy(update={"finding_id": f"syn_005#F{i}"}), case)
        f.case.findings.append(x)
        r = results[i % len(results)]
        f.outcomes.append(Outcome(target=x.id, result=r, learner_label="mass" if r == "mislabeled" else None))
    for j in range(1, n_fp + 1):
        f.learner.marks.append(FactsMark(id=f"M{j}", label="nodule", confidence=3, zone="right_mid_zone"))
        f.outcomes.append(Outcome(target=f"M{j}", result="false_positive", zone="right_mid_zone"))
    return f, case, sub


# --------------------------------------------------------------------------- templates
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_template_row_has_a_sign_and_a_real_sentence_at_every_level(name):
    f, _, _ = facts_for(name)
    cards, zm = load_cards(), load_zone_mimics()
    for level in LEVELS:
        out = _build(f, cards, zm, level)
        _complete(out)
        assert not [e for e in validate(out, f).errors if e.startswith("R9")], (level, validate(out, f).errors)
    _complete(template_debrief(f))
    assert validate(template_debrief(f), f).ok


def test_key_signs_come_from_the_findings_own_card():
    cards = load_cards()
    for name in SCENARIOS:
        f, _, _ = facts_for(name)
        out = template_debrief(f)
        by_id = {x.id: x for x in f.case.findings}
        for row in out.findings:
            signs = cards[by_id[row.finding_id].label].key_signs
            for s in row.what_it_looks_like:
                assert any(s == k or k.startswith(s.split(" (")[0]) for k in signs), (name, s)


@pytest.mark.parametrize(("n", "n_fp"), [(5, 0), (6, 3), (9, 2), (14, 0), (36, 5)])
def test_crowded_templates_stay_complete_and_valid(n, n_fp):
    f, _, _ = _crowded(n, n_fp=n_fp)
    out = template_debrief(f)
    v = validate(out, f)
    assert v.ok, v.errors
    assert len(out.findings) == n and len(out.overcalls) == n_fp
    _complete(out)
    assert total_words(out) <= total_word_limit(f)


@pytest.mark.parametrize("n", [1, 2, 6, 12])
def test_normal_call_on_an_abnormal_film_gets_full_rows(n):
    f, _, _ = _crowded(max(n, 2), declared_normal=True)
    if n == 1:
        f, _, _ = facts_for("missed_recognition")  # syn_003: called normal with confidence 4
    out = template_debrief(f)
    assert out.verdict in ("missed_normal_call", "missed")
    v = validate(out, f)
    assert v.ok, v.errors
    _complete(out)


# --------------------------------------------------------------------------- validator R9 + limits
def test_validator_rejects_empty_signs_and_stub_whys():
    f, _, _ = facts_for("multi")
    good = template_debrief(f).model_dump()
    assert validate(good, f).ok
    empty = json.loads(json.dumps(good))
    empty["findings"][0]["what_it_looks_like"] = []
    e1 = validate(empty, f).errors
    assert len(e1) == 1 and e1[0].startswith("R9 F1.what_it_looks_like has 0 items")
    blank = json.loads(json.dumps(good))
    blank["findings"][0]["what_it_looks_like"] = ["  "]
    assert validate(blank, f).errors[0].startswith("R9 F1.what_it_looks_like has 0 items")
    for stub in ("Never examined.", "Pattern missed.", "You never looked at this."):
        bad = json.loads(json.dumps(good))
        bad["findings"][1]["why"] = stub
        errs = validate(bad, f).errors
        assert len(errs) == 1 and errs[0].startswith(f"R9 F2.why has {len(stub.split())} words"), errs
    ok = json.loads(json.dumps(good))
    ok["findings"][1]["why"] = "Your search never reached this lower area."  # 7 words
    assert validate(ok, f).ok


def test_word_limit_floor_covers_the_mandatory_rows():
    f1, _, _ = facts_for("found")
    f2, _, _ = facts_for("multi")
    assert total_word_limit(f1) == total_word_limit(f2) == 160  # small films: unchanged
    assert total_word_limit(_crowded(4)[0]) == 162 and total_word_limit(_crowded(5)[0]) == 190
    assert total_word_limit(_crowded(10, n_fp=2)[0]) == 50 + 280 + 28
    assert total_word_limit(f2, {"total_max_words": 400}) == 400  # config still wins when it is larger
    assert total_word_limit(f2, {"words_overhead": 10, "words_per_finding": 100}) == 210


# --------------------------------------------------------------------------- live path (mock) + prompt v3
def _run(f, case, sub, client, **kw):
    return service.generate_debrief(
        f, case, attempt_id="a1", submit=sub, client=client, data_root=fixture_root(), offline=False, **kw
    )


def test_prompt_v3_requires_a_sign_and_a_six_word_why_for_every_finding():
    p = load_prompt("debrief_system")
    assert p.version == "v3"
    assert "AT LEAST ONE item" in p.text and "AT LEAST 6 WORDS" in p.text and "DRILL FOCUS" in p.text
    assert "what_it_looks_like = []" not in p.text and "why ≤ 5 words" not in p.text  # the v2 crowded-film budget
    assert 'for "correct"\n   write "correct"' in p.text  # live run 2026-10-06: "right spot" tripped R3 twice
    block = cards_block_text()
    assert "NEVER an empty list" in block and "at least 6 words" in block


def test_stubby_live_debrief_is_regenerated_once_then_accepted():
    f, case, sub = facts_for("multi")
    good = template_debrief(f).model_dump()
    stubby = json.loads(json.dumps(good))
    stubby["findings"][0]["what_it_looks_like"] = []
    stubby["findings"][1]["why"] = "Never examined."
    mc = MockClient([stubby, good])
    r = _run(f, case, sub, mc)
    assert r["source"] == "live" and r["validator"]["regenerated"] and not r["validator"]["first_try_ok"]
    assert len(mc.calls) == 2
    fix = mc.calls[1]["messages"][-1]["content"]
    assert "R9 F1.what_it_looks_like has 0 items" in fix and "R9 F2.why has 2 words" in fix
    assert "at least one what_it_looks_like item" in fix and "at least 6 words" in fix
    _complete(r["debrief"])


def test_side_word_failure_gets_a_plain_instruction_in_the_fix_turn():
    """Live run 2026-10-06 (cxd_56632, mislabeled): 'right' used for 'correct' tripped R3 on both tries."""
    f, case, sub = facts_for("mislabeled")  # syn_001: nodule on the patient's right, called a mass
    good = template_debrief(f).model_dump()
    bad = json.loads(json.dumps(good))
    bad["headline"] = "Left idea, wrong name: the nodule was called a mass."
    assert validate(bad, f).errors[0].startswith("R3 headline: says 'left' about the nodule")
    mc = MockClient([bad, good])
    r = _run(f, case, sub, mc)
    assert r["source"] == "live" and r["validator"]["regenerated"]
    fix = mc.calls[1]["messages"][-1]["content"]
    assert 'if you meant "correct", write "correct"' in fix and "only for the patient's side" in fix


def test_stubby_twice_falls_back_to_a_complete_template():
    f, case, sub = _crowded(7, declared_normal=True)
    stubby = template_debrief(f).model_dump()
    for row in stubby["findings"]:
        row["what_it_looks_like"], row["why"] = [], "Never examined."
    mc = MockClient([stubby, stubby])
    r = _run(f, case, sub, mc)
    assert r["source"] == "template" and r["error"] == "validator_failed" and len(mc.calls) == 2
    assert r["validator"]["ok"] and r["validator"]["fallback_reason"] == "validator_failed"
    assert sum(e.startswith("R9") for e in r["validator"]["attempts"][0]["errors"]) == 14  # 7 signs + 7 whys
    _complete(r["debrief"])


def test_trim_never_removes_the_last_sign():
    f, case, sub = facts_for("multi")
    raw = template_debrief(f).model_dump()
    filler = ["Compare the same place on the other side."] * 30
    for row in raw["findings"]:
        row["what_it_looks_like"] = row["what_it_looks_like"] + filler
    assert total_words(DebriefOutput.model_validate(raw)) > total_word_limit(f)
    mc = MockClient([raw])
    r = _run(f, case, sub, mc)
    assert r["source"] == "live" and r["validator"]["trimmed"] and len(mc.calls) == 1
    assert [len(x.what_it_looks_like) for x in r["debrief"].findings] == [1, 1]
    _complete(r["debrief"])


# --------------------------------------------------------------------------- drill focus
def test_drill_focus_line_leads_the_user_turn_but_facts_still_list_everything():
    f, case, sub = facts_for("multi")  # syn_005: F1 mass (found), F2 nodule (missed)
    good = template_debrief(f, focus_label="nodule").model_dump()
    mc = MockClient([good])
    r = _run(f, case, sub, mc, focus_label="nodule")
    assert r["source"] == "live"
    text = mc.calls[0]["messages"][0]["content"][-1]["text"]
    assert "DRILL FOCUS: nodule (F2)." in text and text.index("DRILL FOCUS") < text.index("FACTS:")
    assert text.endswith("FACTS:\n" + facts_json(f))  # truth unchanged: every finding, focus or not
    assert '"id":"F1"' in text and '"id":"F2"' in text
    assert r["cache_key"] == cache_key_for_facts(f, "mock-model", service.prompt_version(), focus_label="nodule")
    assert r["cache_key"] != cache_key_for_facts(f, "mock-model", service.prompt_version())
    assert {x.finding_id for x in r["debrief"].findings} == {"F1", "F2"}
    # no focus → no line, and the system prefix (cached) is the same either way
    mc2 = MockClient([template_debrief(f).model_dump()])
    _run(f, case, sub, mc2)
    assert "DRILL FOCUS" not in mc2.calls[0]["messages"][0]["content"][-1]["text"]
    assert mc2.calls[0]["system"] == mc.calls[0]["system"]


def test_drill_focus_is_ignored_when_the_film_lacks_the_label():
    for name in ("true_negative", "found"):  # a normal film; a nodule-only film drilled on effusion
        f, case, sub = facts_for(name)
        mc = MockClient([template_debrief(f).model_dump()])
        r = _run(f, case, sub, mc, focus_label="effusion")
        assert "DRILL FOCUS" not in mc.calls[0]["messages"][0]["content"][-1]["text"]
        assert r["cache_key"] == cache_key_for_facts(f, "mock-model", service.prompt_version())


def test_template_headline_leads_with_the_drill_label_on_a_mixed_film():
    f, _, _ = facts_for("multi")
    plain = template_debrief(f)
    focused = template_debrief(f, focus_label="nodule")
    assert plain.headline.startswith("You found 1 of 2 findings")
    assert focused.headline == "Nodule drill: you found 0 of 1; 1 other finding here."
    assert validate(focused, f).ok, validate(focused, f).errors
    assert focused.findings == plain.findings  # rows are the same: every finding, in id order
    one, _, _ = facts_for("bilateral")  # both findings are effusions: the ordinary headline already covers it
    assert template_debrief(one, focus_label="effusion").headline == template_debrief(one).headline
    offline = service.generate_debrief(f, cases()["syn_005"], offline=True, focus_label="nodule")
    assert offline["source"] == "template" and offline["debrief"].headline.startswith("Nodule drill:")


# --------------------------------------------------------------------------- "right" meaning "correct"
@pytest.mark.parametrize(
    "text",
    [
        "Right area, wrong label: thickening called effusion",
        "Right spot, wrong name.",
        "You got it right, but the label needs work.",
        "You were right to pause there.",
        "That's right.",
        "You had the right idea about this opacity.",
        "Mark it right away next time.",
    ],
)
def test_right_meaning_correct_is_rejected_everywhere(text):
    from backend.app.tutor.validator import right_as_correct, validate_ask

    assert right_as_correct(text)
    f, _, _ = facts_for("mislabeled")
    bad = template_debrief(f).model_dump()
    bad["headline"] = text
    errs = validate(bad, f).errors
    assert any(e.startswith("R3 headline:") and 'write "correct"' in e for e in errs), errs
    assert any(e.startswith("R3 answer:") for e in validate_ask(text, f).errors)


@pytest.mark.parametrize(
    "text",
    [
        "Right lower zone, just above the diaphragm.",
        "The nodule sits in the right mid zone, lateral third.",
        "On the patient's right, beside the right hilum.",
        "Right costophrenic angle; compare with the left.",
        "A right-sided effusion blunts the right costophrenic angle.",
        "You marked the correct spot but called it mass.",
        "You left the right apex unvisited.",
    ],
)
def test_patient_side_wording_is_not_mistaken_for_the_idiom(text):
    from backend.app.tutor.validator import right_as_correct

    assert right_as_correct(text) == []


def test_no_template_or_offline_answer_uses_right_for_correct():
    from backend.app.tutor.ask import template_answer
    from backend.app.tutor.validator import right_as_correct, validate_ask

    for name in SCENARIOS:
        f, _, _ = facts_for(name)
        out = template_debrief(f)
        texts = [out.headline, out.search_coaching, out.calibration_note, out.next_step]
        texts += [t for x in out.findings for t in (x.where_to_look, x.why, *x.what_it_looks_like)]
        texts += [t for o in out.overcalls for t in (o.explanation, *o.possible_mimics)]
        assert not [t for t in texts if right_as_correct(t)], name
        for q in ("Why did I get the label wrong?", "Where was it?", "What does it look like?", "Was my mark close?"):
            ans = template_answer(q, f)
            assert not right_as_correct(ans), (name, q, ans)
            assert validate_ask(ans, f).ok, (name, q, validate_ask(ans, f).errors)
