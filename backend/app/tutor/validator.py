"""Deterministic debrief validator (SPEC §8.6). Runs on every debrief, live, cached or templated.

Rules (error strings are prefixed with the rule tag so the faithfulness eval can count them):
  R1 finding ids exactly once, results equal the computed outcomes
  R2 overcall mark ids == false-positive marks
  R3 laterality: left/right words in where_to_look match the finding's side (image-relative phrasing ignored);
     plus a sentence-level check elsewhere: a sentence naming a ground-truth label with only the opposite side word;
     plus "right" used to mean "correct" ("right spot", "got it right") anywhere: next to a location it reads as a
     patient side (live run 2026-10-06: "Right area, wrong label" about a LEFT-sided finding)
  R4 zone vocabulary in where_to_look ⊆ the finding's zones ∪ neighbours ∪ its relative_location; no lobes or rib
     levels (we never compute them)
  R5 label mentions ⊆ ground truth ∪ learner labels ∪ related groups ∪ card/zone-mimic text (catches hallucinations)
  R6 banned content (config regexes + tutor safety list); cm/mm only allowed when pixel_spacing_mm is known
  R7 lengths: headline ≤ headline_max_words, all text ≤ total_max_words
  R8 structure: verdict consistent with outcomes, fact_ids known, required text present, no raw zone ids
  R9 completeness (round 3, UX audit): every finding row has at least one what_it_looks_like item and a `why` of at
     least 6 words (no empty sign lists, no stubs such as "Never examined." or "Pattern missed.")
  R10 drawn signs: a named sign (the engine's sign vocabulary + the schematic names) may appear only when FACTS lists
     it in some finding's signs_drawn or the teaching cards already use those words
validate_ask applies R3 (sentence-level + sided zone phrases), R5, R6 and a 90-word limit.

Volumetric (CT / MR) cases (facts.case.modality ct|mr):
  R2 overcall entries also cover `unmatched` marks; their wording never says wrong / false / incorrect / mistake
     (the reference does not label that spot; public datasets are not exhaustive)
  R4 zone vocabulary adds the volumetric zones (organ, slab third, hemisphere, midline) and their adjacency; slice
     numbers ("slice 9", "slices 7-11") are 1-based like the viewer and must lie within that finding's slice_range
     ± 1 or on a learner mark ± 1 (FACTS indices are 0-based)
  R5 allowed text adds the anatomy explainer cards and the volumetric zone mimics
  R6 mm is allowed only when FACTS carries a size (size_mm, a measurement or a size_verdict) and every "N mm" must be
     one of those numbers (± 1 mm); cm is always banned
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.app.tutor import vocab
from backend.app.tutor.cards import all_zone_mimics, load_anatomy, load_cards, load_zone_mimics
from backend.app.tutor.facts import human_slice
from shared.contracts import DebriefFacts, DebriefOutput, TeachingCard

ASK_MAX_WORDS = 90


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors), "n_errors": len(self.errors)}


# --------------------------------------------------------------------------- text helpers
def words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text or "") if s.strip()]


_IMAGE_RELATIVE = [
    # "the patient's right appears on the left of the image" and variants
    r"\bpatient'?s\s+(?:right|left)(?:\s+side)?\s+(?:appears|is\s+shown|is\s+displayed|shows|sits|is)\s+on\s+the\s+"
    r"(?:image'?s?\s+)?(?:left|right)(?:\s+(?:side\s+)?of\s+the\s+(?:image|film|screen|picture|radiograph|display))?",
    r"\b(?:on\s+)?the\s+(?:left|right)(?:\s+side)?\s+of\s+the\s+(?:image|film|screen|picture|radiograph|display)\b",
    r"\b(?:image|screen|viewer|display|film)(?:'s)?\s+(?:left|right)\b",
    r"\b(?:your|viewer'?s)\s+(?:left|right)\b",
]
_IMAGE_RELATIVE_RE = [re.compile(p, re.I) for p in _IMAGE_RELATIVE]
_SIDE_WORD = re.compile(r"\b(right|left)\b", re.I)


# "right" meaning "correct". In a laterality trainer "Right area, wrong label" about a left-sided finding reads as a
# side, so these idioms are rejected everywhere (debrief fields and ask answers); the fix is to write "correct".
_RIGHT_AS_CORRECT = re.compile(
    r"\bright\s+(?:spot|place|area|region|location|idea|track|call|answer|label|name|instincts?|approach|way|thing"
    r"|choice|diagnosis)\b"
    r"|\b(?:got|get|gets|getting|had|have)\s+(?:it|this|that|them|these|those|both|everything|one)\s+right\b"
    r"|\b(?:you\s+(?:were|are)|you're|that(?:'s|\s+is|\s+was))\s+right\b(?=\s*(?:[.,;:!?]|$|to\b|about\b|that\b))"
    r"|\bright\s+(?:away|now)\b",
    re.I,
)


def right_as_correct(text: str) -> list[str]:
    """Phrases that use "right" to mean "correct" (or "immediately"), e.g. ['Right area']."""
    return [m.group(0) for m in _RIGHT_AS_CORRECT.finditer(text or "")]


def _idiom_errors(field_name: str, text: str) -> list[str]:
    return [
        f'R3 {field_name}: \'{p}\' uses "right" to mean correct; "right" and "left" are read as the patient\'s '
        'side, so write "correct"'
        for p in right_as_correct(text)
    ]


def strip_image_relative(text: str) -> str:
    for p in _IMAGE_RELATIVE_RE:
        text = p.sub(" ", text)
    return text


def side_words(text: str) -> set[str]:
    return {m.lower() for m in _SIDE_WORD.findall(strip_image_relative(text))}


# --------------------------------------------------------------------------- zone vocabulary
# family -> zone ids it can refer to
ZONE_FAMILIES: dict[str, tuple[str, ...]] = {
    "apex": ("right_apex", "left_apex"),
    "hilum": ("right_hilum", "left_hilum"),
    "costophrenic_angle": ("right_costophrenic_angle", "left_costophrenic_angle"),
    "retrocardiac": ("retrocardiac",),
    "upper_zone": ("right_upper_zone", "left_upper_zone"),
    "mid_zone": ("right_mid_zone", "left_mid_zone"),
    "lower_zone": ("right_lower_zone", "left_lower_zone"),
    "periphery": ("right_periphery", "left_periphery"),
    "mediastinum": ("mediastinum",),
    "subdiaphragmatic": ("subdiaphragmatic",),
    # volumetric (CT / MR) zones; "right/left hemisphere" is handled as a sided family below
    "pancreas": ("pancreas",),
    "liver": ("liver",),
    "hepatic_vessels": ("hepatic_vessels",),
    "superior_slab": ("superior_slab",),
    "mid_slab": ("mid_slab",),
    "inferior_slab": ("inferior_slab",),
    "midline_volume": ("midline_volume", "brain_midline"),
    "hemisphere": ("brain_right", "brain_left"),
}
_FAMILY_RE: dict[str, str] = {
    "apex": r"ap(?:ex|ices|ical)",
    "hilum": r"hil(?:um|a|ar)",
    "costophrenic_angle": r"costophrenic(?:\s+angles?)?",
    "retrocardiac": r"retrocardiac|behind\s+the\s+heart",
    "upper_zone": r"upper\s+zones?",
    "mid_zone": r"(?:mid|middle)\s+zones?",
    "lower_zone": r"lower\s+zones?",
    "periphery": r"peripher(?:y|al)",
    "mediastinum": r"mediastin(?:um|al)",
    "subdiaphragmatic": r"(?:sub)?(?:hemi)?diaphragm(?:atic|s)?",
    "pancreas": r"pancreas",
    "liver": r"liver",
    "hepatic_vessels": r"hepatic\s+(?:vessels?|veins?)|portal\s+veins?",
    "superior_slab": r"(?:upper|superior|top)\s+(?:slices|third|slab)",
    "mid_slab": r"(?:middle|mid|central)\s+(?:slices|third|slab)",
    "inferior_slab": r"(?:lower|inferior|bottom)\s+(?:slices|third|slab)",
    "midline_volume": r"midline",
    "hemisphere": r"(?:cerebral\s+)?hemispheres?",
}
_SIDEABLE = {"apex", "hilum", "costophrenic_angle", "upper_zone", "mid_zone", "lower_zone", "periphery", "hemisphere"}
# sided family -> zone id when the id is not "<side>_<family>"
_SIDED_IDS = {"hemisphere": {"right": "brain_right", "left": "brain_left"}}
_FAMILY_COMPILED = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in _FAMILY_RE.items()}
_SIDED_RE = re.compile(
    r"\b(?P<side>right|left)\s+(?:lung\s+)?(?P<term>"
    + "|".join(f"(?P<{k}>{_FAMILY_RE[k]})" for k in sorted(_SIDEABLE))
    + r")\b",
    re.I,
)
_LOBE_RE = re.compile(r"\b(?:upper|middle|lower)\s+lobes?\b|\blingula\w*|\bsegment(?:al)?\s+bronch", re.I)
_RIB_LEVEL_RE = re.compile(
    r"\b(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)"
    r"\s+(?:anterior\s+|posterior\s+)?ribs?\b|\bintercostal\s+spaces?\b|\b(?:T|C)\d{1,2}\b",
    re.I,
)
_RAW_ZONE_ID_RE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
_MR_SEQUENCE_RE = re.compile(r"\bT[12]c?\b|\bFLAIR\b")  # MR sequence names, not vertebral levels


def _no_sequences(text: str, ctx: _Ctx) -> str:
    return _MR_SEQUENCE_RE.sub(" ", text or "") if ctx.volumetric else (text or "")


def zone_mentions(text: str) -> tuple[list[str], list[str]]:
    """(sided zone ids, unsided families) mentioned in text."""
    sided: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _SIDED_RE.finditer(text):
        fam = next(k for k in _SIDEABLE if m.group(k))
        side = m["side"].lower()
        sided.append(_SIDED_IDS.get(fam, {}).get(side, f"{side}_{fam}"))
        spans.append(m.span())
    unsided: list[str] = []
    for fam, rx in _FAMILY_COMPILED.items():
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in spans):
                continue
            unsided.append(fam)
    return sided, unsided


def _zones_with_neighbours(zones: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for z in zones:
        if z:
            out.add(z)
            out |= vocab.neighbors(z)
    return out


_ORGAN_ZONES = {"pancreas", "liver", "hepatic_vessels", "brain_left", "brain_right", "brain_midline"}


def _volumetric_allowed(ff: Any, allowed: set[str], ctx: _Ctx) -> set[str]:
    """Organ zones follow the label, not adjacency: config adjacency links every slab third to the organ zones (an
    organ label may be absent from the mask), so an organ zone is allowed only when it is in FACTS or the label's
    card says the finding hides there and its side matches (a pancreatic tumour in the middle slices may be placed
    "in the pancreas", never "in the liver"; a left brain tumour in the "left cerebral hemisphere" only)."""
    own = set(ff.zones) | ({ff.primary_zone} if ff.primary_zone else set()) | _location_zones(ff.relative_location)
    card = ctx.cards.get(ff.label)
    hides = {z for z in (card.where_it_hides if card else []) if vocab.side_of_zone(z) in (None, ff.side)}
    return {z for z in allowed if z not in _ORGAN_ZONES or z in own} | (hides & _ORGAN_ZONES)


def _location_zones(rel: str | None) -> set[str]:
    if not rel:
        return set()
    sided, unsided = zone_mentions(rel)
    out = set(sided)
    for fam in unsided:
        out |= set(ZONE_FAMILIES[fam])
    return out


# --------------------------------------------------------------------------- label lexicon
LABEL_TERMS: list[tuple[str, str]] = [
    (
        r"\bdiffuse\s+nodul\w*|\bmiliary\b|\b(?:many|multiple|innumerable|numerous|scattered|countless)\s+"
        r"(?:small\s+|tiny\s+)?nodules\b",
        "diffuse_nodule",
    ),
    (r"\bpneumothora(?:x|ces)\b", "pneumothorax"),
    (r"\b(?:pleural\s+)?effusions?\b|\bpleural\s+fluid\b|\bhydrothorax\b|\bha?emothorax\b", "effusion"),
    (r"\bconsolidat\w*|\bairspace\s+(?:disease|opacit\w+)", "consolidation"),
    (r"\batelecta\w*", "atelectasis"),
    (r"\bnodul(?:e|es|ar)\b", "nodule"),
    # volumetric (CT / MR) labels, before the bare "mass / tumour" line below
    (
        r"\bpancrea(?:tic|s)\s+(?:tumou?rs?|mass(?:es)?|lesions?)\b|\btumou?rs?\s+(?:of|in)\s+the\s+pancreas\b",
        "pancreatic_tumour",
    ),
    (
        r"\b(?:liver|hepatic)\s+(?:tumou?rs?|mass(?:es)?|lesions?)\b|\btumou?rs?\s+(?:of|in)\s+the\s+liver\b",
        "liver_tumour",
    ),
    (
        r"\bbrain\s+(?:tumou?rs?|mass(?:es)?|lesions?)\b|\bgliom\w*|\bglioblastom\w*|\btumou?rs?\s+(?:of|in)\s+the\s+brain\b",
        "brain_tumour",
    ),
    (r"\blung\s+tumou?rs?\b|\btumou?rs?\s+(?:of|in)\s+the\s+lungs?\b", "lung_tumour"),
    (
        r"\b(?:colon|colonic|colorectal|bowel|rectal)\s+(?:tumou?rs?|mass(?:es)?)\b|\btumou?rs?\s+(?:of|in)\s+the\s+(?:colon|bowel)\b",
        "colon_tumour",
    ),
    (r"\bmass(?:es)?\b|\btumou?rs?\b", "mass"),
    (r"\bcalcifi\w*", "calcification"),
    (r"\bfractur\w*|\bbroken\s+(?:ribs?|bones?|clavicles?)\b", "fracture"),
    (r"\bpleural\s+thicken\w*|\bthickened\s+pleura\b|\bpleural\s+plaques?\b", "pleural_thickening"),
    (r"\bcardiomegaly\b|\benlarged\s+(?:heart|cardiac)\b|\bheart\s+(?:is\s+)?enlarge\w*", "cardiomegaly"),
    (r"\bemphysema\w*", "emphysema"),
    (r"\bfibros\w*|\bfibrotic\b|\bhoneycomb\w*", "fibrosis"),
]
# Findings outside the taxonomy: never in FACTS, so any mention is a hallucination unless a card uses the term.
OTHER_FINDING_TERMS: list[str] = [
    r"\bpneumonias?\b",
    r"\btuberculo\w*",
    r"\bTB\b",
    r"\bcancers?\b",
    r"\bmalignan\w*",
    r"\bcarcinoma\w*",
    r"\bmetasta\w*",
    r"\blymphoma\w*",
    r"\blymphadenopathy\b",
    r"\b(?:pulmonary\s+)?o?edema\b",
    r"\bheart\s+failure\b",
    r"\bembol\w*",
    r"\binfarct\w*",
    r"\babscess\w*",
    r"\bcavit(?:y|ies|ation|ary)\b",
    r"\bbronchiectasis\b",
    r"\bsarcoid\w*",
    r"\bgranulomas?\b",
    r"\bhamartomas?\b",
    r"\bhernia\w*",
    r"\bpneumomediastinum\b",
    r"\bpneumoperitoneum\b",
    r"\bfree\s+air\b",
    r"\binfiltrat\w*",
    r"\binterstitial\s+lung\s+disease\b",
    r"\bILD\b",
    r"\bCOPD\b",
    r"\bcovid\w*",
    r"\binfections?\b",
    r"\bpacemakers?\b",
    r"\bendotracheal\b",
    r"\bcentral\s+lines?\b",
    r"\bcatheters?\b",
    r"\bnasogastric\b",
    r"\bsternotomy\b",
    r"\bsurgical\s+clips?\b",
    r"\baneurysm\w*",
    r"\bwidened\s+mediastinum\b",
    r"\baortic\s+(?:enlargement|dilat\w*)",
]
_LABEL_RE = [(re.compile(p, re.I), lab) for p, lab in LABEL_TERMS]
_OTHER_RE = [re.compile(p, re.I) for p in OTHER_FINDING_TERMS]


def label_mentions(text: str) -> list[tuple[str, str | None]]:
    """[(matched term, taxonomy label or None for a non-taxonomy finding)]."""
    out: list[tuple[str, str | None]] = []
    t = text or ""
    for rx, lab in _LABEL_RE:
        for m in rx.finditer(t):
            out.append((m.group(0), lab))
        t = rx.sub(" ", t)  # consume so "diffuse nodules" is not also counted as "nodule"
    for rx in _OTHER_RE:
        for m in rx.finditer(t):
            out.append((m.group(0), None))
    return out


# --------------------------------------------------------------------------- drawn signs (R10)
def known_sign_names() -> list[str]:
    """Sign names the tutor could name: the engine's vocabulary (backend/app/signs.py) + schematic names."""
    try:
        from backend.app.signs import SIGN_NAMES, load_schematics

        names = set(SIGN_NAMES.values()) | {s.name for s in load_schematics().values()}
    except Exception:  # noqa: BLE001
        return []
    # generic words that are not signs on their own
    return sorted((n for n in names if n.lower() not in _NOT_A_SIGN), key=len, reverse=True)


_NOT_A_SIGN = {"lesion", "pointer", "pattern extent", "heart width", "chest width", "round opacity", "dense spot"}


def sign_mentions(text: str, names: Iterable[str]) -> list[str]:
    out = []
    t = text or ""
    for n in names:
        if re.search(rf"\b{re.escape(n)}\b", t, re.I):
            out.append(n)
            t = re.sub(rf"\b{re.escape(n)}\b", " ", t, flags=re.I)
    return out


def _sign_errors(field_name: str, text: str, ctx: _Ctx) -> list[str]:
    errs = []
    for n in sign_mentions(text, ctx.sign_names):
        if n.lower() in ctx.drawn_signs or n.lower() in ctx.allowed_text:
            continue
        errs.append(f"R10 {field_name}: names the sign '{n}', which is not drawn on this film (FACTS signs_drawn)")
    return errs


# --------------------------------------------------------------------------- banned content
# Tutor-side safety additions to config/scoring.yaml validator.banned_patterns (management, prognosis, patients).
TUTOR_SAFETY_PATTERNS: list[str] = [
    r"\bprognos\w*",
    r"\bsurg(?:ery|ical|eon)\b",
    r"\bemergenc\w*",
    r"\bprescri\w*",
    r"\bmedications?\b",
    r"\bdiuretic\w*",
    r"\bthora(?:co)?centesis\b",
    r"\bpleurocentesis\b",
    r"\breferral\b",
    r"\bconsultation\b",
    r"\bdischarg(?:e|ed|ing)\s+(?:the\s+)?patient",
    r"\b(?:this|the|your|a)\s+patient\s+(?:has|had|should|needs?|must|will|is|was)\b",
    r"\bdisclaimer\b",
    r"\bnot\s+(?:medical|clinical)\s+advice\b",
    r"\b\d+(?:\.\d+)?\s?(?:inch|inches)\b",
]
_MEASURE_HINT = re.compile(r"cm\|mm|mm\|cm")


_CM_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:cm|centimet\w*)\b|\bcentimet\w*", re.I)
_MM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(?:mm|millimet\w*)\b", re.I)
_SLICE_RE = re.compile(r"\bslices?\s+(\d+)(?:\s*(?:-|–|—|to|through|and)\s*(\d+))?", re.I)
MM_TOLERANCE = 1.0


def _banned_patterns(cfg: dict[str, Any], sizes_allowed: bool) -> list[re.Pattern[str]]:
    pats = []
    for p in list(cfg.get("banned_patterns", [])) + TUTOR_SAFETY_PATTERNS:
        if sizes_allowed and _MEASURE_HINT.search(p):
            continue
        pats.append(re.compile(p, re.I))
    return pats


def banned_hits(text: str, cfg: dict[str, Any], pixel_spacing_known: bool = False) -> list[str]:
    return [m.group(0) for rx in _banned_patterns(cfg, pixel_spacing_known) for m in rx.finditer(text or "")]


def size_numbers_mm(facts: DebriefFacts) -> set[float]:
    """Every size FACTS states in mm: finding size_mm, learner measurements, size_verdict your/reference/diff."""
    out: set[float] = set()
    for f in facts.case.findings:
        if f.size_mm is not None:
            out.add(float(f.size_mm))
    for m in facts.learner.measurements:
        out.add(float(m.long_mm))
    for o in facts.outcomes:
        sv = o.size_verdict or {}
        for k in ("your_mm", "reference_mm", "diff_mm"):
            if sv.get(k) is not None:
                out.add(abs(float(sv[k])))
    return out


def mm_mentions(text: str) -> list[tuple[str, float]]:
    return [(m.group(0), float(m.group(1))) for m in _MM_RE.finditer(text or "")]


def slice_mentions(text: str) -> list[tuple[str, list[int]]]:
    """[("slices 6-10", [6, 10]), ("slice 8", [8])]."""
    out = []
    for m in _SLICE_RE.finditer(text or ""):
        nums = [int(m.group(1))] + ([int(m.group(2))] if m.group(2) else [])
        out.append((m.group(0), nums))
    return out


# --------------------------------------------------------------------------- context derived from FACTS
@dataclass
class _Ctx:
    facts: DebriefFacts
    cards: dict[str, TeachingCard]
    cfg: dict[str, Any]
    zone_mimics: dict[str, Any]

    def __post_init__(self) -> None:
        f = self.facts
        self.findings = {x.id: x for x in f.case.findings}
        self.outcome_by_target = {o.target: o for o in f.outcomes}
        self.mark_ids = {m.id for m in f.learner.marks}
        self.fp_marks = {o.target for o in f.outcomes if o.result == "false_positive" and o.target in self.mark_ids}
        if not self.fp_marks:  # tolerate outcome targets for marks not listed in learner.marks
            self.fp_marks = {o.target for o in f.outcomes if o.result == "false_positive" and o.target[:1] == "M"}
        self.volumetric = vocab.is_volumetric(f.case.modality)
        self.unmatched_marks = {o.target for o in f.outcomes if o.result == "unmatched" and o.target[:1] == "M"}
        self.size_numbers = size_numbers_mm(f)
        self.sizes_allowed = f.case.pixel_spacing_mm is not None or bool(self.size_numbers)
        gt = {x.label for x in f.case.findings}
        learner = {m.label for m in f.learner.marks} | {p.label for p in f.learner.pattern_selections}
        learner |= {o.learner_label for o in f.outcomes if o.learner_label}
        learner &= set(vocab.labels())
        base = gt | learner
        allowed = vocab.related(base)
        for lab in base:
            if lab in self.cards:
                allowed |= set(self.cards[lab].commonly_confused_with)
        if any(lab.endswith("_tumour") for lab in base):
            allowed.add("mass")  # bare "tumour" / "mass" on a CT / MR case refers to the labelled tumour
        self.gt_labels = gt
        self.allowed_labels = allowed
        involved = set(f.teaching_cards) | base
        texts: list[str] = []
        for lab in involved:
            c = self.cards.get(lab)
            if c:
                texts += [c.one_liner, c.search_tip, *c.key_signs, *c.mimics]
        ref_zones = {z for x in f.case.findings for z in x.zones} | {m.zone for m in f.learner.marks if m.zone}
        ref_zones |= {o.zone for o in f.outcomes if o.zone}
        if self.volumetric:
            self.zone_mimics = all_zone_mimics(self.zone_mimics)
            for a in load_anatomy().values():
                texts += [a.display_name, a.one_liner, *a.landmarks, *a.mimics]
        for z in ref_zones:
            texts += list((self.zone_mimics.get("entries") or {}).get(z, []))
        self.allowed_text = " \n ".join(texts).lower()
        self.drawn_signs = {n.lower() for x in f.case.findings for n in (x.signs_drawn or [])}
        self.sign_names = known_sign_names()
        # slice numbers a debrief may write (1-based, as the viewer shows them; FACTS indices are 0-based): per
        # finding its slice_range ± 1, plus the learner's marks ± 1
        self.mark_slices: set[int] = set()
        for m in f.learner.marks:
            if m.slice is not None:
                self.mark_slices |= {human_slice(m.slice) + d for d in (-1, 0, 1)}
        self.finding_slices: dict[str, set[int]] = {}
        for x in f.case.findings:
            if x.slice_range:
                z0, z1 = human_slice(x.slice_range[0]), human_slice(x.slice_range[-1])
                self.finding_slices[x.id] = set(range(z0 - 1, z1 + 2))
        self.all_slices = set().union(*self.finding_slices.values()) | self.mark_slices if self.volumetric else set()
        # zone universe for free-text sided zone phrases (ask answers)
        uni: set[str] = set()
        for x in f.case.findings:
            uni |= _zones_with_neighbours(x.zones + ([x.primary_zone] if x.primary_zone else []))
            uni |= _location_zones(x.relative_location)
        uni |= {m.zone for m in f.learner.marks if m.zone} | {o.zone for o in f.outcomes if o.zone}
        uni |= set(f.search.unvisited_review_areas) | set(f.search.first_visits) | set(vocab.review_area_ids())
        for r in f.spatial_relations:
            uni |= _location_zones(r.text)
        self.zone_universe = uni

    def label_sides(self, label: str) -> set[str]:
        sides: set[str] = set()
        for x in self.facts.case.findings:
            if x.label == label:
                if x.side in ("right", "left"):
                    sides.add(x.side)
                else:
                    sides |= {"right", "left"}
        return sides


def _mentions_mark(sentence: str) -> bool:
    return bool(re.search(r"\bmarks?\b|\bmarked\b|\bM\d+\b|\byou\s+(?:placed|clicked)\b", sentence, re.I))


def _sentence_laterality(field_name: str, text: str, ctx: _Ctx) -> list[str]:
    errs: list[str] = []
    for s in sentences(text):
        if _mentions_mark(s):
            continue
        sw = side_words(s)
        if len(sw) != 1:
            continue
        labs = {lab for _, lab in label_mentions(s) if lab in ctx.gt_labels}
        if not labs:
            continue
        allowed: set[str] = set()
        for lab in labs:
            allowed |= ctx.label_sides(lab)
        bad = sw - allowed
        if bad:
            errs.append(
                f"R3 {field_name}: says '{next(iter(bad))}' about the {', '.join(sorted(labs))}, but FACTS put it "
                f"on the patient's {' and '.join(sorted(allowed))}"
            )
    return errs


def _label_errors(field_name: str, text: str, ctx: _Ctx) -> list[str]:
    errs: list[str] = []
    for term, lab in label_mentions(text):
        if lab is not None and lab in ctx.allowed_labels:
            continue
        if term.lower() in ctx.allowed_text:
            continue
        what = f"label '{lab}'" if lab else "a finding"
        errs.append(f"R5 {field_name}: mentions '{term}' ({what}) that is not in FACTS or the learner's answer")
    return errs


def _banned_errors(field_name: str, text: str, ctx: _Ctx) -> list[str]:
    errs = [f"R6 {field_name}: banned content '{h}'" for h in banned_hits(text, ctx.cfg, ctx.sizes_allowed)]
    if not ctx.volumetric:
        return errs
    for m in _CM_RE.finditer(text or ""):
        errs.append(f"R6 {field_name}: '{m.group(0)}' states centimetres; sizes are always in mm")
    for term, val in mm_mentions(text):
        if not any(abs(val - x) <= MM_TOLERANCE for x in ctx.size_numbers):
            known = ", ".join(f"{x:g} mm" for x in sorted(ctx.size_numbers)) or "none"
            errs.append(f"R6 {field_name}: '{term}' is not a size in FACTS (FACTS sizes: {known})")
    return errs


def _slice_errors(field_name: str, text: str, ctx: _Ctx, finding_id: str | None = None) -> list[str]:
    if not ctx.volumetric:
        return []
    allowed = (ctx.finding_slices.get(finding_id, set()) | ctx.mark_slices) if finding_id else ctx.all_slices
    errs = []
    for term, nums in slice_mentions(text):
        bad = [n for n in nums if n not in allowed]
        if bad:
            what = f"finding {finding_id}'s slices" if finding_id else "the slices FACTS lists"
            errs.append(f"R4 {field_name}: '{term}' names slice {bad[0]}, which is not within {what} or a mark")
    return errs


_UNMATCHED_BANNED = re.compile(r"\bwrong\b|\bfalse\b|\bincorrect\w*|\bmistak\w*|\berror\w*|\bfalse[- ]positive", re.I)


# --------------------------------------------------------------------------- verdicts
def allowed_verdicts(facts: DebriefFacts) -> set[str]:
    res = {o.target: o.result for o in facts.outcomes}
    fids = [f.id for f in facts.case.findings]
    fps = [o for o in facts.outcomes if o.result in ("false_positive", "pattern_false")]
    if facts.case.is_normal or not fids:
        if any(o.result == "true_negative" for o in facts.outcomes) and not fps:
            return {"correct_normal"}
        if facts.learner.declared_normal and not fps:
            return {"correct_normal"}
        return {"overcall", "missed_normal_call"}
    found = sum(res.get(i) in ("found", "pattern_found") for i in fids)
    located = sum(res.get(i) in ("found", "pattern_found", "mislabeled") for i in fids)
    if found == len(fids):
        return {"all_found"}
    if facts.learner.declared_normal:
        return {"missed_normal_call", "missed"}
    if located > 0:
        return {"partly_found"}
    return {"missed"}


# --------------------------------------------------------------------------- main entry points
# R1 lists every finding and R8 needs text for each, so very crowded films (>8 findings; 1.6% of ChestX-Det) get a
# per-finding allowance on top of total_max_words. Config keys override these defaults.
BASE_LIMIT_FINDINGS = 8
WORDS_PER_EXTRA_FINDING = 6
# R9 makes a sign and a full `why` sentence mandatory for EVERY finding, so the limit can never be below what that
# mandatory content needs: overhead (headline, search coaching, calibration, next step) + a row per finding + an entry
# per false-positive mark. Below 5 findings this floor is under total_max_words and changes nothing. Config keys
# (validator.words_overhead / words_per_finding / words_per_overcall / why_min_words / min_signs_per_finding) override.
WORDS_OVERHEAD = 50
WORDS_PER_FINDING = 28
WORDS_PER_OVERCALL = 14
WHY_MIN_WORDS = 6
MIN_SIGNS_PER_FINDING = 1


def total_word_limit(facts: DebriefFacts, cfg: dict[str, Any] | None = None) -> int:
    c = cfg if cfg is not None else vocab.validator_cfg()
    base = int(c.get("total_max_words", 160))
    n0 = int(c.get("total_limit_base_findings", BASE_LIMIT_FINDINGS))
    per = int(c.get("words_per_extra_finding", WORDS_PER_EXTRA_FINDING))
    n = len(facts.case.findings)
    n_fp = sum(o.result in ("false_positive", "unmatched") for o in facts.outcomes)
    mandatory = (
        int(c.get("words_overhead", WORDS_OVERHEAD))
        + int(c.get("words_per_finding", WORDS_PER_FINDING)) * n
        + int(c.get("words_per_overcall", WORDS_PER_OVERCALL)) * n_fp
    )
    return max(base + per * max(0, n - n0), mandatory)


def _text_fields(out: DebriefOutput) -> list[tuple[str, str]]:
    fields = [("headline", out.headline)]
    for f in out.findings:
        fields.append((f"{f.finding_id}.where_to_look", f.where_to_look))
        fields += [(f"{f.finding_id}.what_it_looks_like", s) for s in f.what_it_looks_like]
        fields.append((f"{f.finding_id}.why", f.why))
    for o in out.overcalls:
        fields.append((f"{o.mark_id}.explanation", o.explanation))
        fields += [(f"{o.mark_id}.possible_mimics", s) for s in o.possible_mimics]
    fields += [("search_coaching", out.search_coaching), ("calibration_note", out.calibration_note)]
    fields.append(("next_step", out.next_step))
    return fields


def total_words(output: DebriefOutput) -> int:
    """Words across every text field, exactly as R7 counts them."""
    return sum(words(t) for _, t in _text_fields(output))


def _ctx(
    facts: DebriefFacts,
    cards: dict[str, TeachingCard] | None,
    cfg: dict[str, Any] | None,
    zone_mimics: dict[str, Any] | None,
) -> _Ctx:
    return _Ctx(
        facts=facts,
        cards=cards if cards is not None else load_cards(),
        cfg=cfg if cfg is not None else vocab.validator_cfg(),
        zone_mimics=zone_mimics if zone_mimics is not None else load_zone_mimics(),
    )


def validate(
    output: DebriefOutput | dict[str, Any],
    facts: DebriefFacts,
    cards: dict[str, TeachingCard] | None = None,
    cfg: dict[str, Any] | None = None,
    *,
    zone_mimics: dict[str, Any] | None = None,
) -> ValidationResult:
    """Check a debrief against FACTS. `cfg` is the `validator` section of config/scoring.yaml."""
    if not isinstance(output, DebriefOutput):
        try:
            output = DebriefOutput.model_validate(output)
        except Exception as e:  # noqa: BLE001
            return ValidationResult(False, [f"R0 schema: {str(e).splitlines()[0]}"])
    ctx = _ctx(facts, cards, cfg, zone_mimics)
    errs: list[str] = []

    # R1 findings
    expected = [f.id for f in facts.case.findings]
    counts = Counter(f.finding_id for f in output.findings)
    for fid in expected:
        if counts[fid] == 0:
            errs.append(f"R1: finding {fid} is missing; include every FACTS finding exactly once")
        elif counts[fid] > 1:
            errs.append(f"R1: finding {fid} appears {counts[fid]} times; include it exactly once")
    for fid in counts:
        if fid not in ctx.findings:
            errs.append(f"R1: finding {fid} is not in FACTS; remove it")
    for f in output.findings:
        o = ctx.outcome_by_target.get(f.finding_id)
        if f.finding_id in ctx.findings and o is not None and f.result != o.result:
            errs.append(f"R1: finding {f.finding_id} result is '{f.result}' but FACTS says '{o.result}'")

    # R2 overcalls (false-positive marks; on volumes also the unmatched marks)
    oc = Counter(o.mark_id for o in output.overcalls)
    for mid in sorted(ctx.fp_marks):
        if oc[mid] == 0:
            errs.append(f"R2: false-positive mark {mid} needs an overcall entry")
        elif oc[mid] > 1:
            errs.append(f"R2: overcall {mid} appears {oc[mid]} times")
    for mid in sorted(ctx.unmatched_marks):
        if oc[mid] == 0:
            errs.append(f"R2: unmatched mark {mid} needs an overcall entry saying the reference does not label it")
        elif oc[mid] > 1:
            errs.append(f"R2: overcall {mid} appears {oc[mid]} times")
    for mid in oc:
        if mid not in ctx.fp_marks and mid not in ctx.unmatched_marks:
            errs.append(f"R2: overcall {mid} is not a false-positive or unmatched mark in FACTS; remove it")
    for o in output.overcalls:
        if o.mark_id in ctx.unmatched_marks:
            m = _UNMATCHED_BANNED.search(o.explanation or "")
            if m:
                errs.append(
                    f"R2 {o.mark_id}.explanation: '{m.group(0)}' — an unmatched mark is not wrong; say the "
                    "reference does not label that spot and that public datasets are not exhaustive"
                )
            if not re.search(r"\blabel\w*\b|\breference\b", o.explanation or "", re.I):
                errs.append(f"R2 {o.mark_id}.explanation: say that the reference does not label that spot")

    # R3 + R4 per finding where_to_look
    for f in output.findings:
        ff = ctx.findings.get(f.finding_id)
        if ff is None:
            continue
        where = f.where_to_look or ""
        sw = side_words(where)
        if ff.side in ("right", "left") and sw - {ff.side}:
            errs.append(
                f"R3 {f.finding_id}.where_to_look: says '{', '.join(sorted(sw - {ff.side}))}' but the finding is on "
                f"the patient's {ff.side}"
            )
        sided, unsided = zone_mentions(where)
        if ff.kind == "pattern" and not ff.zones:
            pass  # pattern location is not scored; no zone facts to check against
        else:
            allowed = _zones_with_neighbours(ff.zones + ([ff.primary_zone] if ff.primary_zone else []))
            allowed |= _location_zones(ff.relative_location)
            if ctx.volumetric:
                allowed = _volumetric_allowed(ff, allowed, ctx)
            for z in sided:
                if z not in allowed:
                    errs.append(f"R4 {f.finding_id}.where_to_look: '{vocab.zone_human(z)}' is not where FACTS put it")
            for fam in unsided:
                if not set(ZONE_FAMILIES[fam]) & allowed:
                    errs.append(f"R4 {f.finding_id}.where_to_look: '{fam.replace('_', ' ')}' is not where FACTS put it")
        for rx, what in ((_LOBE_RE, "lobe"), (_RIB_LEVEL_RE, "rib level")):
            for text, name in ((where, "where_to_look"), (f.why, "why")):
                m = rx.search(_no_sequences(text, ctx))
                if m:
                    errs.append(f"R4 {f.finding_id}.{name}: names a {what} ('{m.group(0)}'); FACTS has no {what}s")
        if not where.strip():
            errs.append(f"R8 {f.finding_id}.where_to_look is empty")
        if not (f.why or "").strip():
            errs.append(f"R8 {f.finding_id}.why is empty")
        # R9 completeness: a sign for every finding and a real sentence for why
        min_signs = int(ctx.cfg.get("min_signs_per_finding", MIN_SIGNS_PER_FINDING))
        why_min = int(ctx.cfg.get("why_min_words", WHY_MIN_WORDS))
        n_signs = sum(1 for s in f.what_it_looks_like if (s or "").strip())
        if n_signs < min_signs:
            errs.append(
                f"R9 {f.finding_id}.what_it_looks_like has {n_signs} items; give at least {min_signs} key sign "
                f"from the {ff.display.lower()} card, also for findings the learner found"
            )
        n_why = words(f.why)
        if 0 < n_why < why_min:
            errs.append(
                f"R9 {f.finding_id}.why has {n_why} words ('{f.why.strip()}'); write a full sentence of at least "
                f"{why_min} words about what the learner did there"
            )
        for text, name in (
            (where, "where_to_look"),
            (f.why, "why"),
            *((t, "what_it_looks_like") for t in f.what_it_looks_like),
        ):
            errs += _slice_errors(f"{f.finding_id}.{name}", text, ctx, f.finding_id)

    # R3 (sentence level), R4 lobes, R5, R6 across all text
    for name, text in _text_fields(output):
        if not name.endswith(".where_to_look") and not name.endswith(".possible_mimics"):
            errs += _sentence_laterality(name, text, ctx)
        if not name.endswith(".possible_mimics") and not name.endswith(".where_to_look"):
            m = _LOBE_RE.search(text or "")
            if m:
                errs.append(f"R4 {name}: names a lobe ('{m.group(0)}'); FACTS has no lobes")
        errs += _idiom_errors(name, text)
        errs += _label_errors(name, text, ctx)
        errs += _sign_errors(name, text, ctx)
        errs += _banned_errors(name, text, ctx)
        if not re.match(r"F\d+\.", name):
            errs += _slice_errors(name, text, ctx)
        raw = [w for w in _RAW_ZONE_ID_RE.findall(text or "") if w in set(vocab.all_zone_ids()) | {"not_sure"}]
        if raw:
            errs.append(f"R8 {name}: write zone names in plain words, not ids ('{raw[0]}')")

    # R7 lengths
    vcfg = ctx.cfg
    hmax = int(vcfg.get("headline_max_words", 14))
    tmax = total_word_limit(facts, vcfg)
    if words(output.headline) > hmax:
        errs.append(f"R7: headline has {words(output.headline)} words; maximum {hmax}")
    total = total_words(output)
    if total > tmax:
        errs.append(f"R7: all text fields together have {total} words; maximum {tmax}")

    # R8 verdict, fact_ids, headline present
    av = allowed_verdicts(facts)
    if output.verdict not in av:
        errs.append(f"R8: verdict '{output.verdict}' does not match the outcomes; use {' or '.join(sorted(av))}")
    known_ids = set(ctx.findings) | ctx.mark_ids | {o.target for o in facts.outcomes}
    for fid in output.fact_ids:
        if re.fullmatch(r"[FM]\d+", fid) and fid not in known_ids:
            errs.append(f"R8: fact_ids lists {fid}, which is not in FACTS")
    if not output.headline.strip():
        errs.append("R8: headline is empty")

    errs = list(dict.fromkeys(errs))  # dedupe, keep order
    return ValidationResult(not errs, errs)


def _without_mimic_phrases(text: str, ctx: _Ctx) -> str:
    """Remove verbatim zone-mimic / card-mimic phrases (normal anatomy such as "overlap of the first rib and the
    clavicle") so the rib-level rule only fires on positions the answer invents."""
    raw: list[str] = []
    for ms in (ctx.zone_mimics.get("entries") or {}).values():
        raw += list(ms)
    for c in ctx.cards.values():
        raw += list(c.mimics)
    phrases = {p.strip() for m in raw for p in (m, re.sub(r"\s*\([^)]*\)", "", m)) if p.strip()}
    for p in sorted(phrases, key=len, reverse=True):
        text = re.sub(re.escape(p), " ", text, flags=re.I)
    return text


def validate_ask(
    text: str,
    facts: DebriefFacts,
    cards: dict[str, TeachingCard] | None = None,
    cfg: dict[str, Any] | None = None,
    *,
    zone_mimics: dict[str, Any] | None = None,
    max_words: int = ASK_MAX_WORDS,
) -> ValidationResult:
    """Ask-the-tutor answers: R3 (laterality), R5 (labels), R6 (banned), plus the word limit."""
    ctx = _ctx(facts, cards, cfg, zone_mimics)
    errs: list[str] = []
    if not (text or "").strip():
        errs.append("R8 answer: empty")
    errs += _sentence_laterality("answer", text, ctx)
    errs += _idiom_errors("answer", text)
    sided, _ = zone_mentions(strip_image_relative(text or ""))
    for z in sided:
        if z not in ctx.zone_universe:
            errs.append(f"R3 answer: '{vocab.zone_human(z)}' is not a location in FACTS")
    m = _LOBE_RE.search(text or "") or _RIB_LEVEL_RE.search(_without_mimic_phrases(_no_sequences(text, ctx), ctx))
    if m:
        errs.append(f"R4 answer: names a location FACTS does not have ('{m.group(0)}')")
    errs += _label_errors("answer", text, ctx)
    errs += _sign_errors("answer", text, ctx)
    errs += _banned_errors("answer", text, ctx)
    errs += _slice_errors("answer", text, ctx)
    if words(text) > max_words:
        errs.append(f"R7 answer: {words(text)} words; maximum {max_words}")
    errs = list(dict.fromkeys(errs))
    return ValidationResult(not errs, errs)
