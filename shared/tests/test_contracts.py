"""Contract tests: Pydantic models in shared/contracts.py ↔ JSON Schemas in shared/schemas/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from shared import contracts as c

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _registry() -> Registry:
    reg = Registry()
    for f in SCHEMAS.glob("*.json"):
        doc = json.loads(f.read_text())
        res = Resource.from_contents(doc)
        reg = reg.with_resource(doc["$id"], res).with_resource(f.name, res)
    return reg


def _validator(name: str, pointer: str | None = None) -> Draft202012Validator:
    doc = json.loads((SCHEMAS / name).read_text())
    schema = doc if pointer is None else {"$ref": f"{doc['$id']}#{pointer}"}
    return Draft202012Validator(schema, registry=_registry())


def _check(model, name: str, pointer: str | None = None) -> None:
    data = json.loads(model.model_dump_json(by_alias=True))
    errs = sorted(_validator(name, pointer).iter_errors(data), key=str)
    assert not errs, "\n".join(e.message for e in errs)


FINDING = c.Finding(
    finding_id="cxd_1#F1",
    label="nodule",
    source_label="Nodule",
    kind="focal",
    geometry=c.Geometry(
        kind="polygon", bbox=(10, 10, 50, 50), polygon=[(10, 10), (50, 10), (50, 50)], mask_path="masks/cxd_1#F1.png"
    ),
    centroid=(30.0, 30.0),
    area_frac=0.001,
    side="right",
    zones=["right_lower_zone"],
    primary_zone="right_lower_zone",
    relative_location="right lower zone, lateral third",
)
CASE = c.Case(
    case_id="cxd_1",
    source="chestx-det",
    source_split="train",
    split="practice",
    image_path="images/cxd_1.png",
    width=1024,
    height=1024,
    is_normal=False,
    findings=[FINDING],
    license_tag="NIH-CXR14+ChestX-Det",
    attribution="NIH Clinical Center; Deepwise AI Lab",
    cardiothoracic_ratio=0.5,
)
EVENT = c.TelemetryEvent(t=0, kind="move", x=1.0, y=2.0, zoom=1.0, vp=(0, 0, 1024, 1024), loupe=True)
SUBMIT = c.AttemptSubmit(
    marks=[c.Mark(mark_id="M1", x=30, y=30, label="nodule", confidence=4)],
    patterns=[c.PatternSelection(label="cardiomegaly", confidence=3)],
    declared_normal=False,
    telemetry=[EVENT],
    hints_used=0,
    client_timing=c.ClientTiming(shown_at="2026-10-05T21:00:00Z", submitted_at="2026-10-05T21:00:41Z"),
)
RESULT = c.SubmitResult(
    score=70,
    success=False,
    outcomes=[
        c.Outcome(target="F1", result="missed_search", dwell_ms=120),
        c.Outcome(target="M1", result="false_positive", zone="left_mid_zone"),
    ],
    reveal=c.Reveal(
        findings=[
            c.RevealFinding(
                finding_id="F1",
                label="nodule",
                display="Nodule",
                kind="focal",
                bbox=(10, 10, 50, 50),
                zones=["right_lower_zone"],
                result="missed_search",
            )
        ],
        marks=[c.RevealMark(mark_id="M1", result="false_positive", zone="left_mid_zone")],
        arrows=[c.Arrow(from_mark="M1", to_finding="F1", text="The nodule is in the other lung.")],
        search=c.SearchSummary(lung_coverage_pct=46, unvisited_review_areas=["right_costophrenic_angle"]),
    ),
    facts_card=c.FactsCard(headline="Missed a nodule", lines=["Right lower zone, lateral third."]),
    debrief_status="pending",
)
FACTS = c.DebriefFacts(
    case=c.FactsCase(
        case_id="cxd_1",
        is_normal=False,
        projection="frontal; PA vs AP not recorded",
        findings=[
            c.FactsFinding(
                id="F1",
                label="nodule",
                display="Nodule",
                kind="focal",
                side="right",
                primary_zone="right_lower_zone",
                zones=["right_lower_zone"],
                size="small",
                difficulty="hard",
            )
        ],
    ),
    learner=c.FactsLearner(
        level="MS2",
        declared_normal=False,
        hints_used=0,
        time_to_submit_s=41,
        marks=[c.FactsMark(id="M1", label="nodule", confidence=4, zone="left_mid_zone")],
        pattern_selections=[],
    ),
    outcomes=[c.Outcome(target="F1", result="missed_search", dwell_ms=120)],
    spatial_relations=[c.SpatialRelation(**{"from": "M1", "to": "F1", "text": "The nodule is in the other lung."})],
    search=c.FactsSearch(lung_coverage_pct=46, unvisited_review_areas=["retrocardiac"], first_visits=["right_hilum"]),
    history={"nodule": {"attempts": 6, "localized": 2}, "recent_miss_types": {"search": 3}},
    teaching_cards=["nodule"],
)
DEBRIEF = c.DebriefOutput(
    headline="You never looked at the right lower zone",
    verdict="missed",
    findings=[
        c.DebriefFindingOut(
            finding_id="F1",
            result="missed_search",
            where_to_look="Right lower zone, lateral third.",
            what_it_looks_like=["A small round opacity"],
            why="Your search never paused there.",
        )
    ],
    overcalls=[
        c.DebriefOvercall(mark_id="M1", explanation="Nothing was marked there.", possible_mimics=["Vessel seen end-on"])
    ],
    search_coaching="Finish with the costophrenic angles.",
    calibration_note="",
    next_step="Try another nodule case.",
    fact_ids=["F1", "M1"],
)
CARD = c.TeachingCard(
    label="nodule",
    display_name="Nodule",
    kind="focal",
    one_liner="A round opacity under 3 cm.",
    key_signs=["Round"],
    where_it_hides=["right_apex"],
    mimics=["Nipple shadow"],
    commonly_confused_with=["mass"],
    search_tip="Compare apices.",
    radiopaedia_url=None,
    review=c.CardReview(status="ai_draft", reviewer=None, date=None, notes=None),
)


@pytest.mark.parametrize(
    "model,schema,pointer",
    [
        (FINDING, "finding.json", None),
        (CASE, "case.json", None),
        (EVENT, "telemetry_event.json", None),
        (SUBMIT, "attempt_submit.json", None),
        (RESULT, "submit_result.json", None),
        (FACTS, "debrief_facts.json", None),
        (DEBRIEF, "debrief_output.json", None),
        (
            c.DebriefResponse(status="ready", debrief=DEBRIEF, source="template", provenance="ai_draft"),
            "debrief_response.json",
            None,
        ),
        (CARD, "teaching_card.json", None),
        (c.Health(ok=True, offline=False, cases=3000), "api.json", "/$defs/Health"),
        (c.SessionCreate(display_name="Yash", level="MS2", mode="practice"), "api.json", "/$defs/SessionCreate"),
        (c.SessionCreated(session_id="s1", learner_id="l1", mode="practice"), "api.json", "/$defs/SessionCreated"),
        (
            c.NextCase(
                attempt_id="a1",
                case=c.NextCaseCase(case_id="cxd_1", image_url="/api/cases/cxd_1/image", width=1024, height=1024),
                index=1,
            ),
            "api.json",
            "/$defs/NextCase",
        ),
        (c.HintRequest(marks=[], telemetry=[EVENT]), "api.json", "/$defs/HintRequest"),
        (
            c.HintResponse(level=1, text="You haven't looked at: right apex.", remaining=2),
            "api.json",
            "/$defs/HintResponse",
        ),
        (c.AskRequest(question="Why is air dark?"), "api.json", "/$defs/AskRequest"),
        (c.AskResponse(answer="Air attenuates few X-rays.", remaining=2), "api.json", "/$defs/AskResponse"),
        (c.AssessmentRecorded(index=1, total=20), "api.json", "/$defs/AssessmentRecorded"),
        (
            c.AssessmentSummary(
                session_id="s",
                mode="assess_A",
                n_cases=20,
                sensitivity=0.5,
                specificity=0.9,
                localization_fraction=0.4,
                false_positives_per_image=0.3,
                miss_type_mix={"search": 2},
                score_mean=60.0,
            ),
            "api.json",
            "/$defs/AssessmentSummary",
        ),
        (
            c.ReviewRating(
                reviewer="Dr X",
                role="radiologist",
                item_type="debrief",
                item_id="d1",
                accuracy=5,
                teaching=4,
                safety_flag=False,
            ),
            "api.json",
            "/$defs/ReviewRating",
        ),
        (c.SusSubmit(learner_id="l1", answers=[3] * 10), "api.json", "/$defs/SusSubmit"),
    ],
)
def test_model_matches_schema(model, schema, pointer):
    _check(model, schema, pointer)


def test_next_case_has_no_ground_truth_keys():
    nc = c.NextCase(attempt_id="a", case=c.NextCaseCase(case_id="x", image_url="u", width=1, height=1), index=0)
    keys = set(json.loads(nc.model_dump_json()).keys()) | set(nc.case.model_dump().keys())
    assert not (keys & c.GROUND_TRUTH_KEYS)


def test_schema_files_are_valid_json_schema():
    for f in SCHEMAS.glob("*.json"):
        Draft202012Validator.check_schema(json.loads(f.read_text()))
