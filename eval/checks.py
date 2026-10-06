"""Deterministic debrief checks owned by the eval (an independent re-implementation of SPEC §8.6 rules 1–7).

Used for (a) the eval's own laterality / out-of-scope-label / banned-content statistics in BOTH conditions, so the
numbers do not depend on the production validator being evaluated, and (b) a stand-in validator when
backend.app.tutor.validator is not available (always labeled in reports).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from eval.common import REPO_ROOT
from shared.contracts import DebriefFacts, DebriefOutput

# ------------------------------------------------------------------------------------------------ vocab
# Order matters: multi-word / more specific labels first so their spans are removed before shorter matches.
LABEL_PATTERNS: list[tuple[str, str]] = [
    ("diffuse_nodule", r"\bdiffuse(ly)?\s+nodul(e|es|ar)\b|\bmiliary\b"),
    ("pleural_thickening", r"\bpleural\s+thickening\b|\bthickened\s+pleura\b"),
    ("pneumothorax", r"\bpneumothora(x|ces)\b"),
    ("effusion", r"\beffusions?\b"),
    ("consolidation", r"\bconsolidat(ion|ions|ed)\b"),
    ("atelectasis", r"\batelecta(sis|ses|tic)\b"),
    ("nodule", r"\bnodules?\b|\bnodular\b"),
    ("mass", r"\bmass(es)?\b"),
    ("calcification", r"\bcalcifi(cation|cations|ed)\b"),
    ("fracture", r"\bfractur(e|es|ed)\b"),
    ("cardiomegaly", r"\bcardiomegaly\b|\benlarged\s+heart\b"),
    ("emphysema", r"\bemphysema(tous)?\b"),
    ("fibrosis", r"\bfibros(is|es)\b|\bfibrotic\b"),
]
_LABEL_RX = [(lab, re.compile(rx, re.I)) for lab, rx in LABEL_PATTERNS]

# Phrases about the display convention or image orientation are not laterality claims.
_ORIENTATION_RX = [
    re.compile(
        r"(patient'?s\s+)?(right|left)\s+(side\s+)?(appears|is\s+shown|is\s+displayed|shows)\s+on\s+the\s+"
        r"(left|right)(\s+side)?(\s+of\s+the\s+(image|screen|film|display))?",
        re.I,
    ),
    re.compile(r"\bon\s+the\s+(left|right)(\s+side)?\s+of\s+the\s+(image|screen|film|display)\b", re.I),
    re.compile(r"\b(image|screen|film)[-\s](left|right)\b", re.I),
    re.compile(r"\b(left|right)[-\s]hand\s+side\s+of\s+the\s+(image|screen|film)\b", re.I),
    re.compile(r"\b(left|right)\s+of\s+the\s+(image|screen|film)\b", re.I),
]

# zone vocabulary → zone id template ({s} = side)
ZONE_TERMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bap(ex|ices|ical)\b", re.I), "{s}_apex"),
    (re.compile(r"\bhil(um|a|ar)\b", re.I), "{s}_hilum"),
    (re.compile(r"\bcostophrenic\b", re.I), "{s}_costophrenic_angle"),
    (re.compile(r"\bretrocardiac\b|\bbehind\s+the\s+heart\b", re.I), "retrocardiac"),
    (re.compile(r"\bupper\s+zone\b", re.I), "{s}_upper_zone"),
    (re.compile(r"\b(mid|middle)\s+zone\b", re.I), "{s}_mid_zone"),
    (re.compile(r"\blower\s+zone\b", re.I), "{s}_lower_zone"),
    (re.compile(r"\bperipher(y|al)\b", re.I), "{s}_periphery"),
    (re.compile(r"\bmediastin(um|al)\b", re.I), "mediastinum"),
    (re.compile(r"\bdiaphragm\w*\b", re.I), "subdiaphragmatic"),
]


@lru_cache
def _scoring_cfg() -> dict[str, Any]:
    from backend.app import config

    return config.scoring()


@lru_cache
def _adjacency() -> dict[str, list[str]]:
    from backend.app import config

    return dict(config.review_areas().get("adjacency", {}))


@lru_cache
def _related() -> tuple[frozenset[str], ...]:
    from backend.app import config

    return config.related_groups()


@lru_cache
def _schema() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "shared" / "schemas" / "debrief_output.json").read_text())


def banned_patterns(pixel_spacing_known: bool) -> list[tuple[str, re.Pattern[str]]]:
    """(category, regex) from config/scoring.yaml validator.banned_patterns."""
    out = []
    for p in _scoring_cfg().get("validator", {}).get("banned_patterns", []):
        if "cm|mm" in p:
            if pixel_spacing_known:
                continue
            cat = "measurement"
        elif "patient" in p:
            cat = "real_patient"
        else:
            cat = "management"
        out.append((cat, re.compile(p, re.I)))
    return out


def mentioned_labels(text: str) -> list[str]:
    found: list[str] = []
    t = text
    for lab, rx in _LABEL_RX:
        if rx.search(t):
            found.append(lab)
            t = rx.sub(" ", t)
    return found


def strip_orientation(text: str) -> str:
    for rx in _ORIENTATION_RX:
        text = rx.sub(" ", text)
    return text


def sides_mentioned(text: str) -> set[str]:
    t = strip_orientation(text)
    out = set()
    if re.search(r"\bright\b", t, re.I):
        out.add("right")
    if re.search(r"\bleft\b", t, re.I):
        out.add("left")
    return out


def text_fields(o: dict[str, Any]) -> list[str]:
    parts = [o.get("headline", ""), o.get("search_coaching", ""), o.get("calibration_note", ""), o.get("next_step", "")]
    for f in o.get("findings", []) or []:
        parts += [f.get("where_to_look", ""), f.get("why", "")] + list(f.get("what_it_looks_like", []) or [])
    for c in o.get("overcalls", []) or []:
        parts += [c.get("explanation", "")] + list(c.get("possible_mimics", []) or [])
    return [p for p in parts if isinstance(p, str)]


def word_count(s: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", s))


def short_id(x: str) -> str:
    return x.split("#", 1)[1] if "#" in x else x


# ------------------------------------------------------------------------------------------------ result
@dataclass
class CheckResult:
    schema_ok: bool
    schema_errors: list[str] = field(default_factory=list)
    ids_ok: bool = True
    results_ok: bool = True
    result_mismatches: list[str] = field(default_factory=list)
    overcalls_ok: bool = True
    laterality_errors: list[str] = field(default_factory=list)
    zone_errors: list[str] = field(default_factory=list)
    out_of_scope_labels: list[str] = field(default_factory=list)
    banned: dict[str, list[str]] = field(default_factory=dict)
    headline_words: int = 0
    total_words: int = 0
    length_ok: bool = True

    @property
    def management(self) -> bool:
        return bool(self.banned.get("management") or self.banned.get("real_patient"))

    @property
    def errors(self) -> list[str]:
        e = [f"schema: {s}" for s in self.schema_errors]
        if not self.ids_ok:
            e.append("finding ids do not match FACTS")
        e += [f"result: {m}" for m in self.result_mismatches]
        if not self.overcalls_ok:
            e.append("overcall mark ids do not match the false-positive marks")
        e += [f"laterality: {m}" for m in self.laterality_errors]
        e += [f"zone: {m}" for m in self.zone_errors]
        e += [f"label not allowed: {m}" for m in self.out_of_scope_labels]
        for cat, hits in self.banned.items():
            e += [f"banned ({cat}): {h}" for h in hits]
        if not self.length_ok:
            e.append(f"length: headline {self.headline_words} words, total {self.total_words} words")
        return e

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        d["management"] = self.management
        return d


def check_debrief(
    output: dict[str, Any] | None, facts: DebriefFacts, *, cards: dict[str, Any] | None = None
) -> CheckResult:
    """All deterministic checks for one debrief against the FACTS of its scenario."""
    if output is None:
        return CheckResult(
            schema_ok=False, schema_errors=["no parseable output"], ids_ok=False, results_ok=False, overcalls_ok=False
        )
    v = jsonschema.Draft202012Validator(_schema())
    schema_errors = [e.message for e in v.iter_errors(output)][:5]
    try:
        DebriefOutput.model_validate(output)
    except Exception as e:  # noqa: BLE001 — record any validation failure as data
        schema_errors.append(f"pydantic: {str(e).splitlines()[0]}")
    res = CheckResult(schema_ok=not schema_errors, schema_errors=schema_errors)
    findings_out = [f for f in output.get("findings", []) or [] if isinstance(f, dict)]
    overcalls_out = [c for c in output.get("overcalls", []) or [] if isinstance(c, dict)]

    # rule 1: ids and results
    facts_ids = [f.id for f in facts.case.findings]
    out_ids = [short_id(str(f.get("finding_id", ""))) for f in findings_out]
    res.ids_ok = sorted(out_ids) == sorted(facts_ids)
    truth = {short_id(o.target): o.result for o in facts.outcomes}
    for f in findings_out:
        fid = short_id(str(f.get("finding_id", "")))
        if fid in truth and f.get("result") != truth[fid]:
            res.result_mismatches.append(f"{fid}: said {f.get('result')}, FACTS {truth[fid]}")
    res.results_ok = not res.result_mismatches and res.ids_ok

    # rule 2: overcalls == false-positive marks
    fps = sorted(short_id(o.target) for o in facts.outcomes if o.result == "false_positive")
    res.overcalls_ok = sorted(short_id(str(c.get("mark_id", ""))) for c in overcalls_out) == fps

    # rules 3–4: laterality and zone vocabulary in where_to_look
    by_id = {f.id: f for f in facts.case.findings}
    adj = _adjacency()
    for f in findings_out:
        fid = short_id(str(f.get("finding_id", "")))
        ff = by_id.get(fid)
        where = str(f.get("where_to_look", ""))
        if ff is None:
            continue
        said = sides_mentioned(where)
        if ff.side == "right" and "left" in said:
            res.laterality_errors.append(f"{fid} is on the patient's right; where_to_look says left")
        if ff.side == "left" and "right" in said:
            res.laterality_errors.append(f"{fid} is on the patient's left; where_to_look says right")
        allowed = set(ff.zones) | ({ff.primary_zone} if ff.primary_zone else set())
        for z in list(allowed):
            allowed |= set(adj.get(z, []))
        if not allowed or ff.kind == "pattern":
            continue
        sides = [ff.side] if ff.side in ("right", "left") else ["right", "left"]
        text = strip_orientation(where)
        for rx, tmpl in ZONE_TERMS:
            if rx.search(text):
                cands = {tmpl.format(s=s) for s in sides}
                if not cands & allowed:
                    res.zone_errors.append(f"{fid}: '{rx.search(text).group(0)}' not among its zones/neighbours")

    # rule 5: label mentions must be in scope
    allowed_labels = {f.label for f in facts.case.findings}
    allowed_labels |= {m.label for m in facts.learner.marks if m.label != "not_sure"}
    allowed_labels |= {p.label for p in facts.learner.pattern_selections}
    for g in _related():
        if g & allowed_labels:
            allowed_labels |= set(g)
    for lab in list(allowed_labels):
        card = (cards or {}).get(lab)
        if card is None:
            continue
        cc = card.get("commonly_confused_with", []) if isinstance(card, dict) else card.commonly_confused_with
        mim = card.get("mimics", []) if isinstance(card, dict) else card.mimics
        allowed_labels |= set(cc or [])
        for m in mim or []:
            allowed_labels |= set(mentioned_labels(m))
    all_text = " \n".join(text_fields(output))
    res.out_of_scope_labels = sorted(set(mentioned_labels(all_text)) - allowed_labels)

    # rule 6: banned content
    for cat, rx in banned_patterns(facts.case.pixel_spacing_mm is not None):
        hits = [m.group(0) for m in rx.finditer(all_text)]
        if hits:
            res.banned.setdefault(cat, []).extend(hits)

    # rule 7: lengths
    vcfg = _scoring_cfg().get("validator", {})
    res.headline_words = word_count(str(output.get("headline", "")))
    res.total_words = sum(word_count(t) for t in text_fields(output))
    res.length_ok = res.headline_words <= int(vcfg.get("headline_max_words", 14)) and res.total_words <= int(
        vcfg.get("total_max_words", 160)
    )
    return res


def validate(output: dict[str, Any], facts: DebriefFacts, cards: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stand-in validator with the production return shape used by eval.adapters.normalize_validator."""
    r = check_debrief(output, facts, cards=cards)
    return {"ok": r.ok, "errors": r.errors, "raw": r.as_dict()}


def load_schema_path() -> Path:
    return REPO_ROOT / "shared" / "schemas" / "debrief_output.json"
