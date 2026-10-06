"""Pydantic mirrors of shared/schemas/*.json. FROZEN CONTRACT — owned by the orchestrator.

Subagents import from here; they never edit it. Changes go through a CONTRACT CHANGE REQUEST
in docs/PROGRESS.md. shared/tests/test_contracts.py checks these models against the JSON Schemas.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- vocabularies
Label = Literal[
    "pneumothorax",
    "effusion",
    "consolidation",
    "atelectasis",
    "nodule",
    "mass",
    "calcification",
    "fracture",
    "pleural_thickening",
    "cardiomegaly",
    "emphysema",
    "fibrosis",
    "diffuse_nodule",
]
FocalLabel = Literal[
    "pneumothorax",
    "effusion",
    "consolidation",
    "atelectasis",
    "nodule",
    "mass",
    "calcification",
    "fracture",
    "pleural_thickening",
]
PatternLabel = Literal["cardiomegaly", "emphysema", "fibrosis", "diffuse_nodule"]
LearnerFocalLabel = Literal[
    "pneumothorax",
    "effusion",
    "consolidation",
    "atelectasis",
    "nodule",
    "mass",
    "calcification",
    "fracture",
    "pleural_thickening",
    "not_sure",
]
Side = Literal["right", "left", "bilateral", "midline"]
Kind = Literal["focal", "pattern"]
Split = Literal["practice", "assess_A", "assess_B", "bench", "holdout"]
Mode = Literal["practice", "drill", "assess_A", "assess_B", "review"]
Level = Literal["MS1", "MS2", "MS3", "MS4", "intern", "resident", "PA/NP student", "other"]
Confidence = Literal[1, 2, 3, 4, 5]
OutcomeResult = Literal[
    "found",
    "mislabeled",
    "missed_search",
    "missed_recognition",
    "missed_decision",
    "pattern_found",
    "pattern_missed",
    "pattern_false",
    "true_positive",
    "duplicate",
    "false_positive",
    "true_negative",
]
DebriefFindingResult = Literal[
    "found",
    "mislabeled",
    "missed_search",
    "missed_recognition",
    "missed_decision",
    "pattern_found",
    "pattern_missed",
]
Verdict = Literal["all_found", "partly_found", "missed", "overcall", "correct_normal", "missed_normal_call"]
ReviewStatus = Literal["ai_draft", "student_reviewed", "radiologist_reviewed"]
DebriefSource = Literal["live", "cache", "template"]

XY = tuple[float, float]
BBox = tuple[float, float, float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- case.json / finding.json
class Geometry(_Strict):
    kind: Literal["polygon", "bbox"]
    bbox: BBox
    polygon: list[XY] | None = None
    mask_path: str | None = None


class Finding(_Strict):
    finding_id: str
    label: Label
    source_label: str
    kind: Kind
    geometry: Geometry
    centroid: XY
    area_frac: float = Field(ge=0, le=1)
    side: Side | None = None
    zones: list[str] = []
    primary_zone: str | None = None
    relative_location: str | None = None
    contrast: float | None = None
    model_prob: float | None = None
    edge_dist: float | None = None
    difficulty: float | None = None
    readers: int | None = None
    agreement: float | None = None

    @property
    def short_id(self) -> str:
        return self.finding_id.split("#", 1)[1]


class Case(_Strict):
    case_id: str
    source: Literal["chestx-det", "vindr-cxr", "nih-bbox", "synthetic"]
    source_split: str
    split: Split
    image_path: str
    width: int
    height: int
    pixel_spacing_mm: float | None = None
    is_normal: bool
    findings: list[Finding]
    anatomy_path: str | None = None
    zones_path: str | None = None
    zones_approximate: bool = False
    cardiothoracic_ratio: float | None = None
    difficulty_prior: float = 0.0
    features: dict[str, float] = {}
    license_tag: str
    attribution: str
    qa_flags: list[str] = []


# --------------------------------------------------------------------------- telemetry_event.json
TelemetryKind = Literal["move", "down", "up", "wheel", "enter", "leave", "loupe", "wl", "pan"]


class TelemetryEvent(_Strict):
    t: float = Field(ge=0)
    kind: TelemetryKind
    x: float | None = None
    y: float | None = None
    zoom: float = Field(ge=0)
    vp: BBox
    loupe: bool


# --------------------------------------------------------------------------- attempt_submit.json
class Mark(_Strict):
    mark_id: str
    x: float
    y: float
    label: LearnerFocalLabel
    confidence: Confidence


class PatternSelection(_Strict):
    label: PatternLabel
    confidence: Confidence


class ClientTiming(_Strict):
    shown_at: str
    submitted_at: str


class AttemptSubmit(_Strict):
    marks: list[Mark]
    patterns: list[PatternSelection]
    declared_normal: bool
    normal_confidence: Confidence | None = None
    telemetry: list[TelemetryEvent] = Field(max_length=20000)
    hints_used: int = Field(ge=0, le=3)
    client_timing: ClientTiming


# --------------------------------------------------------------------------- submit_result.json
class Outcome(_Strict):
    target: str
    result: OutcomeResult
    dwell_ms: float | None = None
    zone: str | None = None
    matched: str | None = None
    learner_label: str | None = None


class RevealFinding(_Strict):
    finding_id: str
    label: str
    display: str
    kind: Kind
    polygon: list[XY] | None = None
    bbox: BBox
    centroid: XY | None = None
    side: str | None = None
    zones: list[str]
    primary_zone: str | None = None
    relative_location: str | None = None
    result: OutcomeResult | None = None
    dwell_ms: float | None = None


class RevealMark(_Strict):
    mark_id: str
    result: Literal["true_positive", "duplicate", "false_positive"]
    matched_finding: str | None = None
    zone: str | None = None


class Arrow(_Strict):
    from_mark: str | None
    to_finding: str
    text: str
    from_xy: XY | None = None
    to_xy: XY | None = None


class SearchSummary(_Strict):
    lung_coverage_pct: float
    unvisited_review_areas: list[str]
    visited_review_areas: list[str] = []
    first_visits: list[str] = []
    time_to_first_mark_s: float | None = None
    total_time_s: float | None = None
    zoom_used: bool = False
    loupe_used: bool = False
    heatmap_png_b64: str | None = None


class Reveal(_Strict):
    findings: list[RevealFinding]
    marks: list[RevealMark]
    arrows: list[Arrow]
    search: SearchSummary
    ctr: float | None = None
    is_normal: bool = False
    zones_approximate: bool = False


class FactsCard(_Strict):
    headline: str
    lines: list[str]


class SubmitResult(_Strict):
    score: float = Field(ge=0, le=100)
    success: bool
    outcomes: list[Outcome]
    reveal: Reveal
    facts_card: FactsCard
    debrief_status: Literal["pending", "disabled"]


class AssessmentRecorded(_Strict):
    recorded: Literal[True] = True
    index: int | None = None
    total: int | None = None


# --------------------------------------------------------------------------- debrief_facts.json
class FactsFinding(_Strict):
    id: str
    label: str
    display: str
    kind: Kind
    side: str | None = None
    primary_zone: str | None = None
    zones: list[str] = []
    relative_location: str | None = None
    size: str | None = None
    difficulty: Literal["easy", "moderate", "hard"] | None = None
    zones_approximate: bool = False
    ctr: float | None = None


class FactsCase(_Strict):
    case_id: str
    is_normal: bool
    projection: str
    pixel_spacing_mm: float | None = None
    findings: list[FactsFinding]


class FactsMark(_Strict):
    id: str
    label: str
    confidence: int
    zone: str | None


class FactsPattern(_Strict):
    label: str
    confidence: int


class FactsLearner(_Strict):
    level: str
    declared_normal: bool
    normal_confidence: int | None = None
    hints_used: int
    time_to_submit_s: float
    marks: list[FactsMark]
    pattern_selections: list[FactsPattern]


class SpatialRelation(_Strict):
    from_: str = Field(alias="from")
    to: str
    text: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class FactsSearch(_Strict):
    lung_coverage_pct: float
    unvisited_review_areas: list[str]
    first_visits: list[str]
    zoom_used: bool = False
    loupe_used: bool = False


class DebriefFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_: Literal["debrief_facts.v1"] = Field(default="debrief_facts.v1", alias="schema")
    case: FactsCase
    learner: FactsLearner
    outcomes: list[Outcome]
    spatial_relations: list[SpatialRelation]
    search: FactsSearch
    history: dict[str, Any]
    teaching_cards: list[str]

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


# --------------------------------------------------------------------------- debrief_output.json
class DebriefFindingOut(_Strict):
    finding_id: str
    result: DebriefFindingResult
    where_to_look: str
    what_it_looks_like: list[str]
    why: str


class DebriefOvercall(_Strict):
    mark_id: str
    explanation: str
    possible_mimics: list[str]


class DebriefOutput(_Strict):
    headline: str
    verdict: Verdict
    findings: list[DebriefFindingOut]
    overcalls: list[DebriefOvercall]
    search_coaching: str
    calibration_note: str
    next_step: str
    fact_ids: list[str]


class DebriefResponse(_Strict):
    status: Literal["pending", "ready", "failed", "disabled"]
    debrief: DebriefOutput | None = None
    source: DebriefSource | None = None
    provenance: ReviewStatus | None = None
    validator: dict[str, Any] | None = None
    latency_ms: float | None = None
    error: str | None = None


# --------------------------------------------------------------------------- teaching_card.json
class CardReview(_Strict):
    status: ReviewStatus
    reviewer: str | None
    date: str | None
    notes: str | None


class TeachingCard(_Strict):
    label: str
    display_name: str
    kind: Kind
    one_liner: str
    key_signs: list[str] = Field(min_length=1)
    where_it_hides: list[str]
    mimics: list[str]
    commonly_confused_with: list[str]
    search_tip: str
    radiopaedia_url: str | None
    review: CardReview


# --------------------------------------------------------------------------- api.json
class Health(_Strict):
    ok: bool
    offline: bool
    cases: int
    version: str | None = None


class SessionCreate(_Strict):
    display_name: str = Field(min_length=1, max_length=80)
    level: Level
    participant_code: str | None = None
    mode: Mode
    settings: dict[str, Any] = {}


class SessionCreated(_Strict):
    session_id: str
    learner_id: str
    mode: Mode


class NextCaseCase(_Strict):
    case_id: str
    image_url: str
    width: int
    height: int


class NextCase(_Strict):
    """INVARIANT: never contains ground truth."""

    attempt_id: str
    case: NextCaseCase
    index: int
    total: int | None = None
    hints_enabled: bool = True
    done: bool = False


class HintRequest(_Strict):
    marks: list[Mark]
    telemetry: list[TelemetryEvent]


class HintResponse(_Strict):
    level: int = Field(ge=1, le=3)
    text: str
    remaining: int = Field(ge=0)


class AskRequest(_Strict):
    question: str = Field(min_length=1, max_length=500)


class AskResponse(_Strict):
    answer: str
    remaining: int
    source: Literal["live", "template"] = "live"


class AssessmentSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str
    mode: Mode
    n_cases: int
    sensitivity: float | None
    specificity: float | None
    localization_fraction: float | None
    false_positives_per_image: float
    miss_type_mix: dict[str, int]
    score_mean: float
    cases: list[dict[str, Any]] = []


class ReviewRating(_Strict):
    reviewer: str
    role: str
    item_type: Literal["debrief", "card"]
    item_id: str
    accuracy: int = Field(ge=1, le=5)
    teaching: int = Field(ge=1, le=5)
    safety_flag: bool
    comment: str | None = None
    card_edits: dict[str, Any] | None = None


class SusSubmit(_Strict):
    learner_id: str
    answers: list[int] = Field(min_length=10, max_length=10)


class SusResult(_Strict):
    score: float


# Ground-truth field names that must never appear in pre-submit responses (used by leak tests).
GROUND_TRUTH_KEYS: frozenset[str] = frozenset(
    {
        "findings",
        "is_normal",
        "label",
        "polygon",
        "mask_path",
        "zones",
        "primary_zone",
        "side",
        "relative_location",
        "difficulty_prior",
        "cardiothoracic_ratio",
        "anatomy_path",
        "zones_path",
        "centroid",
        "area_frac",
        "source_label",
        "qa_flags",
        "outcomes",
        "reveal",
        "facts_card",
    }
)
