"""Facts builder (SPEC §8.1) on synthetic fixtures: schema-valid, deterministic, code-built strings only."""

import json
import re

import jsonschema
import pytest

from backend.app.tests._tutor_helpers import SCENARIOS, cases, facts_for, submit
from backend.app.tutor import vocab
from backend.app.tutor.facts import PROJECTION, build_facts, difficulty_word, size_text
from shared.contracts import Outcome

SCHEMA = json.loads((vocab.SCHEMAS_DIR / "debrief_facts.json").read_text())


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_facts_validate_against_schema(name):
    f, case, _ = facts_for(name)
    doc = json.loads(f.model_dump_json(by_alias=True))
    jsonschema.validate(doc, SCHEMA)
    assert doc["schema"] == "debrief_facts.v1"
    assert doc["case"]["projection"] == PROJECTION
    assert [x["id"] for x in doc["case"]["findings"]] == [g.short_id for g in case.findings]
    assert not re.search(r"\d\s?(cm|mm)\b", json.dumps(doc)), "never centimetres without pixel spacing"


def test_facts_focal_fields_are_code_built():
    f, case, _ = facts_for("found")
    ff = f.case.findings[0]
    src = case.findings[0]
    assert (ff.id, ff.label, ff.display, ff.kind) == ("F1", "nodule", "Nodule", "focal")
    assert ff.side == "right" == src.side
    assert ff.zones == src.zones and ff.primary_zone == src.primary_zone
    assert ff.relative_location == src.relative_location
    assert ff.size == "medium (about 0.23% of the image)"
    assert ff.difficulty == "hard" and ff.ctr is None
    assert f.learner.marks[0].zone == "right_mid_zone"
    assert f.learner.time_to_submit_s == 41.0


def test_patient_side_convention_in_facts():
    """Patient right is displayed on the image left: right-sided findings have centroid x < W/2."""
    for name in SCENARIOS:
        f, case, _ = facts_for(name)
        for ff, src in zip(f.case.findings, case.findings, strict=True):
            if ff.side == "right":
                assert src.centroid[0] < case.width / 2
            if ff.side == "left":
                assert src.centroid[0] > case.width / 2


def test_pattern_finding_has_ctr_and_no_size():
    f, _, _ = facts_for("pattern_found")
    ff = f.case.findings[0]
    assert ff.kind == "pattern" and ff.ctr == 0.62 and ff.size is None and ff.relative_location is None


def test_teaching_cards_include_learner_labels_and_history_is_filtered():
    hist = {
        "nodule": {"attempts": 6, "localized": 2},
        "fracture": {"attempts": 1, "localized": 0},
        "recent_miss_types": {"search": 3, "recognition": 1, "decision": 0},
    }
    f, _, _ = facts_for("mislabeled", history=hist)
    assert f.teaching_cards == ["nodule", "mass"]
    assert set(f.history) == {"nodule", "recent_miss_types"}
    f2, _, _ = facts_for("pattern_false_normal")
    assert f2.teaching_cards == ["emphysema"]
    f3, _, _ = facts_for("true_negative")
    assert f3.teaching_cards == []


def test_relations_and_full_ids_are_normalized():
    f, _, _ = facts_for("missed_decision")  # relation given as {"from_mark", "to_finding"}
    r = f.spatial_relations[0]
    assert (r.from_, r.to) == ("M1", "F1")
    assert json.loads(f.model_dump_json(by_alias=True))["spatial_relations"][0]["from"] == "M1"
    c = cases()["syn_001"]
    outs = [Outcome(target="syn_001#F1", result="missed_search", dwell_ms=10.0)]
    g = build_facts(
        case=c,
        submit=submit([], declared_normal=True),
        outcomes=outs,
        spatial_relations=[{"from_mark": None, "to_finding": "F1", "text": "x"}],
        search={"lung_coverage_pct": 10, "unvisited_review_areas": []},
        mark_zones={},
        level="MS3",
        history={},
    )
    assert g.outcomes[0].target == "F1" and g.spatial_relations == [] and g.learner.level == "MS3"


def test_build_facts_is_deterministic():
    a, _, _ = facts_for("multi")
    b, _, _ = facts_for("multi")
    assert a.model_dump_json(by_alias=True) == b.model_dump_json(by_alias=True)


def test_size_and_difficulty_words():
    assert size_text(0.0005) == "small (about 0.05% of the image)"
    assert size_text(0.0123).startswith("medium (about 1.2%")
    assert size_text(0.0882).startswith("large (about 8.8%")
    assert (difficulty_word(-1.0), difficulty_word(0.0), difficulty_word(0.7), difficulty_word(None)) == (
        "easy",
        "moderate",
        "hard",
        None,
    )
