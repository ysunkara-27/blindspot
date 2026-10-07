"""Template debrief pieces for volumetric (CT / MR) cases: filled only from FACTS + card fields.

Used by templates._build when facts.case.modality is ct or mr. Every string is code-built: locations are the
finding's relative_location (zone, patient's side, slice range), sizes come from size_mm / the learner's
measurement / the size_verdict and are always in mm, `why` lines map the miss type to slice behaviour, and an
`unmatched` mark is reported as "the reference does not label that spot" (never wrong, never guessed at).
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.tutor import vocab
from backend.app.tutor.cards import zone_mimics_for
from backend.app.tutor.facts import human_slice
from shared.contracts import DebriefFacts, DebriefOvercall, FactsFinding, Outcome, TeachingCard

GENERIC_SIGN = "An area whose attenuation or enhancement differs from the organ around it"
_MISS_ORDER = ("missed_search", "missed_recognition", "missed_decision", "mislabeled")
NEXT_STEP = {
    "missed_search": "On the next volume, scroll through every slice from top to bottom before you place a mark.",
    "missed_recognition": "On the next volume, pause on each slice where the organ changes shape and compare it with "
    "the neighbouring slices.",
    "missed_decision": "On the next volume, compare anything borderline with the same structure on neighbouring "
    "slices and on the other side.",
    "mislabeled": "On the next volume, check which organ the finding sits in before you choose a label.",
    "overcall": "On the next volume, follow a suspicious spot across neighbouring slices: vessels become tubes, "
    "findings stay round.",
    "ok": "Keep scrolling through every slice on the next volume.",
}
UNMATCHED_NOTE = "public datasets are not exhaustive, so this mark is reported, not counted"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _lc_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s and not (len(s) > 1 and s[1].isupper()) else s  # keep "T1c", "CT", "MR"


def _strip_paren(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


def _sentence(s: str) -> str:
    s = s.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _mm(x: float) -> str:
    return f"{float(x):g} mm"


def slice_text(f: FactsFinding) -> str | None:
    """'slices 7-11' / 'slice 9' (1-based for the learner) from the 0-based FACTS slice_range; the total lives in
    relative_location."""
    if not f.slice_range:
        return None
    z0, z1 = human_slice(f.slice_range[0]), human_slice(f.slice_range[-1])
    return f"slice {z0}" if z0 == z1 else f"slices {z0}-{z1}"


def mark_slice(facts: DebriefFacts, o: Outcome | None) -> int | None:
    if o is None or not o.matched:
        return None
    m = next((m for m in facts.learner.marks if m.id == o.matched), None)
    return human_slice(m.slice) if m is not None and m.slice is not None else None  # 1-based for the learner


# --------------------------------------------------------------------------- size verdict
def size_sentence(o: Outcome | None) -> str | None:
    """'You measured 12 mm; the reference measures 13.5 mm — within tolerance.' /
    '... — 26% smaller than the reference.' Only from the outcome's size_verdict (code-built by the backend)."""
    sv = (o.size_verdict or {}) if o is not None else {}
    if sv.get("your_mm") is None or sv.get("reference_mm") is None:
        return None
    your, ref = float(sv["your_mm"]), float(sv["reference_mm"])
    head = f"You measured {_mm(your)}; the reference measures {_mm(ref)}"
    if sv.get("ok"):
        return f"{head} — within tolerance."
    pct = sv.get("diff_pct")
    if pct is None and ref:
        pct = 100.0 * (your - ref) / ref
    if pct is None:
        return f"{head}."
    word = "smaller" if float(pct) < 0 else "larger"
    return f"{head} — {abs(round(float(pct))):g}% {word} than the reference."


def size_fact_sentence(f: FactsFinding) -> str | None:
    """'The reference measures 13.5 mm (long axis).' when FACTS carries size_mm; else None."""
    return f"The reference measures {_mm(f.size_mm)} (long axis)." if f.size_mm is not None else None


# --------------------------------------------------------------------------- per finding
def where(f: FactsFinding, level: str) -> str:
    """relative_location as FACTS built it (zone, patient's side, slice range); shorter at lower levels."""
    if level in ("minimal", "tiny"):
        base = vocab.zone_human(f.primary_zone) if f.primary_zone else (f.relative_location or "see the outline")
        sl = slice_text(f)
        return _sentence(_cap(f"{base}, {sl}" if sl else base))
    if f.relative_location:
        return _sentence(_cap(f.relative_location))
    return "See the outline on the slices."


def what(f: FactsFinding, result: str, card: TeachingCard | None, level: str, n_findings: int = 1) -> list[str]:
    """1-2 key signs from the label's card (CT / MR language); plus the labelled components at full level.
    CT / MR signs are long sentences, so two signs only on single-finding volumes."""
    if not card or not card.key_signs:
        signs = [GENERIC_SIGN]
    else:
        n = 2 if level == "full" and result != "found" and n_findings == 1 else 1
        signs = [s if level == "full" else _strip_paren(s) for s in card.key_signs[:n]]
    if level == "full" and f.components:
        signs.append("Reference components: " + ", ".join(f.components))
    if level in ("full", "short") and f.signs_drawn:
        name = f.signs_drawn[0]
        signs = [f"Look at the {name[:1].lower()}{name[1:]} drawn on the slice", *signs[:2]]
    return signs


def why(
    facts: DebriefFacts,
    f: FactsFinding,
    o: Outcome | None,
    result: str,
    card: TeachingCard | None,
    learner_label: str | None,
    level: str,
    cards: dict[str, TeachingCard],
) -> str:
    sl = slice_text(f) or "its slices"
    sign = _lc_first(card.key_signs[0]) if card and card.key_signs else None
    tip = card.search_tip if card else None
    ms = mark_slice(facts, o)
    on_slice = f" on slice {ms}" if ms is not None else ""
    if result == "found":
        base = f"You marked it{on_slice} and named it correctly."
        size = size_sentence(o)
        return f"{base} {size}" if size and level in ("full", "short") else base
    if result == "mislabeled":
        other = vocab.display(learner_label or "not_sure").lower()
        base = f"You marked the correct spot{on_slice} but called it {other}."
        lc = cards.get(learner_label or "")
        if level == "full" and card and lc:
            return f"{base} {f.display}: {_lc_first(card.one_liner)} {lc.display_name}: {_lc_first(lc.one_liner)}"
        return base
    if result == "missed_search":
        base = f"You never scrolled to {sl}, where the reference labels it."
        return f"{base} {tip}" if level == "full" and tip else base
    if result == "missed_recognition":
        secs = f" ({o.dwell_ms / 1000.0:.1f} s)" if o is not None and o.dwell_ms else ""
        base = f"{_cap(sl)} were on screen only briefly{secs}, and your cursor never settled on it."
        if sl.startswith("slice "):
            base = f"{_cap(sl)} was on screen only briefly{secs}, and your cursor never settled on it."
        return f"{base} Look for {sign}" + ("" if sign.endswith(".") else ".") if level == "full" and sign else base
    if result == "missed_decision":
        base = f"You lingered on {sl} and judged them normal."
        if sl.startswith("slice "):
            base = f"You lingered on {sl} and judged it normal."
        if level == "full" and card and card.mimics:
            return f"{base} A common look-alike is {_lc_first(_strip_paren(card.mimics[0]))}."
        return base
    return "See the outline on the slices."


# --------------------------------------------------------------------------- whole-debrief pieces
def _with_article(label: str) -> str:
    d = vocab.display(label).lower()
    return ("an " if d[0] in "aeiou" else "a ") + d


def headline(facts: DebriefFacts, verdict: str, n_found: int) -> str:
    fs = facts.case.findings
    n = len(fs)
    what_ = _with_article(fs[0].label) if n == 1 else f"{n} findings"
    if verdict == "all_found":
        return (
            f"Well spotted: you found the {vocab.display(fs[0].label).lower()}."
            if n == 1
            else (f"You found all {n} findings.")
        )
    if verdict == "partly_found":
        res = {o.target: o.result for o in facts.outcomes}
        n_mislabeled = sum(res.get(f.id) == "mislabeled" for f in fs)
        if n_found == n and n_mislabeled:
            if n == 1:
                return "You found it, but the label needs another look."
            s = "s need" if n_mislabeled != 1 else " needs"
            return f"You found all {n} findings, but {n_mislabeled} label{s} another look."
        return f"You found {n_found} of {n} findings; here is where to scroll."
    if verdict == "missed":
        return f"This volume had {what_}; here is where to scroll."
    if verdict == "missed_normal_call":
        if facts.case.is_normal:
            return "The reference labels nothing here, but you did not call it normal."
        return f"You called this volume normal, but it had {what_}."
    if verdict == "overcall":
        if any(o.result == "false_positive" for o in facts.outcomes):
            return "The reference labels nothing here; your mark is not on a labelled finding."
        return "The reference labels nothing here; your mark is unmatched, not counted."
    return "Correct: the reference labels nothing here, and you called it normal."


def search_coaching(facts: DebriefFacts, level: str) -> str:
    un = list(facts.search.unvisited_review_areas)
    pct = facts.search.slices_viewed_pct
    seen = f"You viewed {pct:g}% of the slices" if pct is not None else "You scrolled the slices"
    if not un:
        base = f"{seen} and visited every review area."
        return f"{base} Keep that route on every volume." if level == "full" else base
    if level in ("minimal", "tiny"):
        return f"{seen} and skipped {len(un)} review area{'s' if len(un) != 1 else ''}."
    names = [vocab.zone_human(z) for z in un[:3]]
    more = f" and {len(un) - 3} more" if len(un) > 3 else ""
    listed = (", ".join(names[:-1]) + " and the " + names[-1]) if len(names) > 1 else names[0]
    base = f"{seen} and skipped the {listed}{more}."
    return f"{base} Scroll through every slice at the organ window before you mark." if level == "full" else base


def calibration(facts: DebriefFacts) -> str:
    res = {o.target: o for o in facts.outcomes}
    for m in facts.learner.marks:
        o = res.get(m.id)
        if o and o.result == "false_positive" and m.confidence >= 4:
            return f"You rated {m.id} {m.confidence}/5 confident, but the reference labels nothing there."
    nc = facts.learner.normal_confidence
    if facts.learner.declared_normal and facts.case.findings and nc is not None and nc >= 4:
        return f"You called it normal with confidence {nc}/5; confident misses are worth noticing."
    return ""


def overcalls(facts: DebriefFacts, cards: dict[str, TeachingCard], level: str) -> list[DebriefOvercall]:
    out: list[DebriefOvercall] = []
    marks = {m.id: m for m in facts.learner.marks}
    for o in facts.outcomes:
        if o.result not in ("false_positive", "unmatched"):
            continue
        m = marks.get(o.target)
        zone = o.zone or (m.zone if m else None)
        where_ = f" ({vocab.zone_human(zone)})" if zone else ""
        if o.result == "unmatched":
            expl = f"The reference does not label the spot where you placed {o.target}{where_}; {UNMATCHED_NOTE}."
            if level in ("minimal", "tiny"):
                expl = f"The reference does not label the spot at {o.target}; it is reported, not counted."
            out.append(DebriefOvercall(mark_id=o.target, explanation=expl, possible_mimics=[]))
            continue
        expl = f"The reference labels nothing where you placed {o.target}{where_}."
        if level == "tiny":
            expl = f"Nothing labelled at {o.target}."
        mimics = [_strip_paren(x) for x in zone_mimics_for(zone)[:2]]
        lab = m.label if m else None
        if lab and lab in cards:
            mimics += [_strip_paren(x) for x in cards[lab].mimics[:1]]
            if level == "full":
                expl += f" Normal structures there can look like {_with_article(lab)}."
        out.append(
            DebriefOvercall(
                mark_id=o.target, explanation=expl, possible_mimics=mimics[: (1 if level in ("minimal", "tiny") else 3)]
            )
        )
    return out


def next_step(facts: DebriefFacts) -> str:
    res = {o.target: o.result for o in facts.outcomes}
    for r in _MISS_ORDER:
        if any(res.get(f.id) == r for f in facts.case.findings):
            return NEXT_STEP[r]
    if any(o.result in ("false_positive", "unmatched") for o in facts.outcomes):
        return NEXT_STEP["overcall"]
    return NEXT_STEP["ok"]


def fact_ids(facts: DebriefFacts) -> list[str]:
    ids = [f.id for f in facts.case.findings]
    ids += [o.target for o in facts.outcomes if o.result in ("false_positive", "unmatched")]
    return ids


def pieces(facts: DebriefFacts, cards: dict[str, TeachingCard], level: str) -> dict[str, Any]:
    """Everything templates._build needs for a volumetric debrief, keyed by DebriefOutput field."""
    return {
        "overcalls": overcalls(facts, cards, level),
        "search_coaching": search_coaching(facts, level),
        "calibration_note": calibration(facts),
        "next_step": next_step(facts),
        "fact_ids": fact_ids(facts),
    }
