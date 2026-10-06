"""Template debriefs (SPEC §8.7): one per result type, filled only from FACTS + card fields.

Used offline, when the API fails, or when a live debrief fails the validator twice. Every template must pass the
validator (tested on every fixture scenario). Wording avoids side words except inside code-built location strings.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.tutor import vocab
from backend.app.tutor.cards import load_cards, load_zone_mimics
from backend.app.tutor.validator import allowed_verdicts, total_word_limit, validate, words
from shared.contracts import DebriefFacts, DebriefFindingOut, DebriefOutput, DebriefOvercall, FactsFinding, TeachingCard

LEVELS = ("full", "short", "minimal", "tiny")  # tiny: crowded films, chip-style wording
_COUNTABLE = {"pneumothorax", "effusion", "nodule", "mass", "calcification", "fracture"}
_MISS_ORDER = ("missed_search", "missed_recognition", "missed_decision", "mislabeled", "pattern_missed")
_NEXT_STEP = {
    "missed_search": "On the next film, visit every review area before you place your first mark.",
    "missed_recognition": "On the next film, pause the loupe on each region and compare it with the other side.",
    "missed_decision": "On the next film, compare anything borderline with the same spot on the other side.",
    "mislabeled": "On the next film, check the key signs before you choose a label.",
    "pattern_missed": "On the next film, run through the Global findings checklist before you submit.",
    "overcall": "On the next film, check whether a spot matches a normal structure before marking it.",
    "ok": "Keep the same search route on the next film.",
}
_ROUTE = "apices, hila, behind the heart, costophrenic angles, below the diaphragm"


def _lc_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


def _strip_paren(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


def _sentence(s: str) -> str:
    s = s.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _name(label: str) -> str:
    """'the nodule', 'the pleural effusion', 'cardiomegaly' (lower case display)."""
    d = vocab.display(label).lower()
    return f"the {d}" if label in _COUNTABLE else d


def with_article(label: str) -> str:
    d = vocab.display(label).lower()
    if label not in _COUNTABLE:
        return d
    return ("an " if d[0] in "aeiou" else "a ") + d


_CHIP = {
    "found": "Found it.",
    "mislabeled": "Found it, named it wrong.",
    "missed_search": "Never looked there.",
    "missed_recognition": "Looked past it.",
    "missed_decision": "Looked, judged it normal.",
    "pattern_found": "Ticked it.",
    "pattern_missed": "Not ticked.",
}


def _where(f: FactsFinding, level: str) -> str:
    if level == "tiny":
        if f.kind == "pattern":
            return "Heart against chest width." if f.label == "cardiomegaly" else "Both lungs overall."
        loc = vocab.zone_human(f.primary_zone) if f.primary_zone else None
        return _sentence(loc[:1].upper() + loc[1:]) if loc else "See the outline."
    if f.kind == "pattern":
        if f.label == "cardiomegaly":
            ctr = f" (automatic CTR {f.ctr:.2f}; AP films exaggerate heart size)" if f.ctr is not None else ""
            return (
                "Heart width against the inner chest width" + (ctr if level == "full" or level == "short" else "") + "."
            )
        return "Both lungs as a whole, compared side to side and top to bottom."
    if level == "minimal" or not f.relative_location:
        loc = vocab.zone_human(f.primary_zone) if f.primary_zone else None
        if loc:
            return _sentence(loc[:1].upper() + loc[1:])
    if f.relative_location:
        return _sentence(f.relative_location[:1].upper() + f.relative_location[1:])
    return "See the cyan outline on the image."


def _zone_phrase(f: FactsFinding) -> str:
    return vocab.zone_human(f.primary_zone) if f.primary_zone else "that area"


def _why(
    f: FactsFinding,
    result: str,
    card: TeachingCard | None,
    learner_label: str | None,
    level: str,
    cards: dict[str, TeachingCard],
) -> str:
    if level == "tiny":
        return _CHIP.get(result, "See the outline.")
    sign = _lc_first(card.key_signs[0]) if card and card.key_signs else None
    tip = card.search_tip if card else None
    zone = _zone_phrase(f)
    if result == "found":
        return "You marked it and named it correctly."
    if result == "pattern_found":
        return "You ticked it in Global findings."
    if result == "mislabeled":
        other = vocab.display(learner_label or "not_sure")
        base = f"You marked the correct spot but called it {other.lower()}."
        if level != "full" or learner_label in (None, "not_sure"):
            return base
        lc = cards.get(learner_label or "")
        if card and lc:
            return f"{base} {f.display}: {_lc_first(card.one_liner)} {lc.display_name}: {_lc_first(lc.one_liner)}"
        return base
    if result == "missed_search":
        base = f"Your search never paused in the {zone}."
        return f"{base} {tip}" if level == "full" and tip else base
    if result == "missed_recognition":
        base = f"Your cursor crossed the {zone} only briefly."
        return f"{base} Look for {sign}" + ("" if sign.endswith(".") else ".") if level == "full" and sign else base
    if result == "missed_decision":
        base = f"You looked at the {zone} for a while and judged it normal."
        if level == "full" and card and card.mimics:
            return f"{base} A common look-alike is {_lc_first(_strip_paren(card.mimics[0]))}."
        return base
    if result == "pattern_missed":
        base = f"You did not tick {f.display.lower()} in Global findings."
        return f"{base} {tip}" if level == "full" and tip else base
    return "See the outline on the image."


def _what(f: FactsFinding, result: str, card: TeachingCard | None, level: str) -> list[str]:
    if not card:
        return []
    n = {"full": 2, "short": 1, "minimal": 0, "tiny": 0}[level]
    if result in ("found", "pattern_found"):
        n = min(n, 1)
    return [_strip_paren(s) if level != "full" else s for s in card.key_signs[:n]]


def _headline(facts: DebriefFacts, verdict: str, n_found: int) -> str:
    fs = facts.case.findings
    n = len(fs)
    what = with_article(fs[0].label) if n == 1 else f"{n} findings"
    if verdict == "all_found":
        return f"Well spotted: you found {_name(fs[0].label)}." if n == 1 else f"You found all {n} findings."
    if verdict == "partly_found":
        # n_found counts localized findings (found + mislabeled + pattern_found), like backend/app/facts_card.py
        res = {o.target: o.result for o in facts.outcomes}
        n_mislabeled = sum(res.get(f.id) == "mislabeled" for f in fs)
        if n_found == n and n_mislabeled:
            if n == 1:
                return "You found it, but the label needs another look."
            s = "s need" if n_mislabeled != 1 else " needs"
            return f"You found all {n} findings, but {n_mislabeled} label{s} another look."
        return f"You found {n_found} of {n} findings; here is where to look."
    if verdict == "missed":
        return f"This film had {what}; here is where to look."
    if verdict == "missed_normal_call":
        if facts.case.is_normal:
            return "This film is normal, but you did not call it normal."
        return f"You called this film normal, but it had {what}."
    if verdict == "overcall":
        if facts.learner.marks:
            return "This film is normal; radiologists marked nothing where you clicked."
        return "This film is normal; radiologists did not mark what you ticked."
    return "Correct: this film is normal, and you called it normal."


def _search_coaching(facts: DebriefFacts, level: str) -> str:
    un = list(facts.search.unvisited_review_areas)
    if not un:
        return "You visited every review area; keep that route on every film."
    if level in ("minimal", "tiny"):
        return f"Your search skipped {len(un)} review area{'s' if len(un) != 1 else ''}."
    names = [vocab.zone_human(z) for z in un[:4]]
    more = f" and {len(un) - 4} more" if len(un) > 4 else ""
    listed = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else names[0]
    base = f"Your search skipped the {listed}{more}."
    return f"{base} Use one route on every film: {_ROUTE}." if level == "full" else base


def _calibration(facts: DebriefFacts) -> str:
    res = {o.target: o for o in facts.outcomes}
    for m in facts.learner.marks:
        o = res.get(m.id)
        if o and o.result == "false_positive" and m.confidence >= 4:
            return f"You rated {m.id} {m.confidence}/5 confident, but radiologists marked nothing there."
    nc = facts.learner.normal_confidence
    if facts.learner.declared_normal and facts.case.findings and nc is not None and nc >= 4:
        return f"You called it normal with confidence {nc}/5; confident misses are worth noticing."
    return ""


def _overcalls(
    facts: DebriefFacts, cards: dict[str, TeachingCard], zm: dict[str, Any], level: str
) -> list[DebriefOvercall]:
    out: list[DebriefOvercall] = []
    marks = {m.id: m for m in facts.learner.marks}
    for o in facts.outcomes:
        if o.result != "false_positive":
            continue
        m = marks.get(o.target)
        zone = o.zone or (m.zone if m else None)
        where = f" ({vocab.zone_human(zone)})" if zone else ""
        expl = f"Radiologists marked nothing where you placed {o.target}{where}."
        if level == "tiny":
            expl = f"Nothing marked at {o.target}."
        mimics = list((zm.get("entries") or {}).get(zone or "", []))[:2]
        lab = m.label if m else None
        if lab and lab in cards:
            mimics += [_strip_paren(x) for x in cards[lab].mimics[:1]]
            if level == "full":
                expl += f" Normal structures there can look like {with_article(lab)}."
        out.append(
            DebriefOvercall(
                mark_id=o.target, explanation=expl, possible_mimics=mimics[: (1 if level in ("minimal", "tiny") else 3)]
            )
        )
    return out


def _next_step(facts: DebriefFacts) -> str:
    res = {o.target: o.result for o in facts.outcomes}
    for r in _MISS_ORDER:
        if any(res.get(f.id) == r for f in facts.case.findings):
            return _NEXT_STEP[r]
    if any(o.result in ("false_positive", "pattern_false") for o in facts.outcomes):
        return _NEXT_STEP["overcall"]
    return _NEXT_STEP["ok"]


def _build(facts: DebriefFacts, cards: dict[str, TeachingCard], zm: dict[str, Any], level: str) -> DebriefOutput:
    res = {o.target: o for o in facts.outcomes}
    verdicts = allowed_verdicts(facts)
    pref = ("all_found", "partly_found", "overcall", "missed_normal_call", "missed", "correct_normal")
    verdict = next(v for v in pref if v in verdicts)
    findings: list[DebriefFindingOut] = []
    n_found = 0
    for f in facts.case.findings:
        o = res.get(f.id)
        result = o.result if o else ("pattern_missed" if f.kind == "pattern" else "missed_search")
        n_found += result in ("found", "mislabeled", "pattern_found")
        card = cards.get(f.label)
        findings.append(
            DebriefFindingOut(
                finding_id=f.id,
                result=result,  # type: ignore[arg-type]
                where_to_look=_where(f, level),
                what_it_looks_like=_what(f, result, card, level),
                why=_why(f, result, card, o.learner_label if o else None, level, cards),
            )
        )
    fact_ids = [f.id for f in facts.case.findings] + [o.target for o in facts.outcomes if o.result == "false_positive"]
    return DebriefOutput(
        headline=_headline(facts, verdict, n_found),
        verdict=verdict,  # type: ignore[arg-type]
        findings=findings,
        overcalls=_overcalls(facts, cards, zm, level),
        search_coaching=_search_coaching(facts, level),
        calibration_note=_calibration(facts),
        next_step=_next_step(facts),
        fact_ids=fact_ids,
    )


def _total_words(out: DebriefOutput) -> int:
    parts = [out.headline, out.search_coaching, out.calibration_note, out.next_step]
    for f in out.findings:
        parts += [f.where_to_look, f.why, *f.what_it_looks_like]
    for o in out.overcalls:
        parts += [o.explanation, *o.possible_mimics]
    return sum(words(p) for p in parts)


def template_debrief(
    facts: DebriefFacts,
    cards: dict[str, TeachingCard] | None = None,
    zone_mimics: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> DebriefOutput:
    """Deterministic debrief from FACTS + cards. Shortens itself until it fits the validator's word limits."""
    cards = cards if cards is not None else load_cards()
    zm = zone_mimics if zone_mimics is not None else load_zone_mimics()
    limit = total_word_limit(facts, cfg)
    out = None
    for level in LEVELS:
        out = _build(facts, cards, zm, level)
        if _total_words(out) <= limit and validate(out, facts, cards, cfg, zone_mimics=zm).ok:
            return out
    assert out is not None
    return out
