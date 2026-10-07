"""Ask the tutor (SPEC §8.9): up to 3 follow-up questions per case, same FACTS and images.

Live answers are validated (R3 laterality, R5 labels, R6 banned content, ≤ 90 words); any failure, offline mode,
or API error returns a deterministic template answer built from FACTS + cards.

Volumetric (CT / MR) cases: "where" answers give the zone, patient's side and slice range from FACTS; "how big"
answers give size_mm / the learner's measurement / the size verdict (mm only); "why missed" uses the slice-based
why lines; unmatched marks are reported as "the reference does not label that spot"; anatomy questions ("what is the
pancreas") answer from the anatomy explainer cards.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.app.settings import get_settings
from backend.app.tutor import analytics, vocab
from backend.app.tutor import cards as cards_mod
from backend.app.tutor import templates_volume as tv
from backend.app.tutor.client import (
    ASK_MAX_TOKENS,
    ASK_SCHEMA,
    AnthropicTutorClient,
    LiveCallError,
    as_tutor_client,
    fallback_error,
    system_blocks,
    user_content,
)
from backend.app.tutor.facts import facts_json
from backend.app.tutor.guard import guarded_complete
from backend.app.tutor.prompts import load_prompt
from backend.app.tutor.render import ordered
from backend.app.tutor.templates import why_sentence, with_article
from backend.app.tutor.validator import ASK_MAX_WORDS, label_mentions, validate_ask, words
from shared.contracts import AskResponse, Case, DebriefFacts, FactsFinding, Outcome, TeachingCard

log = logging.getLogger("blindspot.tutor.ask")

_MANAGEMENT_Q = re.compile(
    r"\b(treat\w*|manag\w*|therap\w*|drugs?|medication\w*|antibiotic\w*|surgery|should\s+(?:i|we|they)\s+do|"
    r"what\s+(?:do|should)\s+(?:i|we)\s+do|next\s+steps?\s+for\s+the\s+patient|prognos\w*|admit\w*)\b",
    re.I,
)
REFUSE_MANAGEMENT = (
    "This trainer teaches how to see findings on the film, not what to do clinically. "
    "Ask me how to recognise or find what the radiologists marked."
)


OFFLINE_HELP = (
    "Offline: I can only answer from this case's facts and the teaching cards. "
    "Try asking where it was, what it looks like, or why it was missed."
)

# Keyword rules, checked in this order (first match wins). Deterministic; no model involved.
_INTENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "mimic",
        re.compile(
            r"\bmimic\w*|\blook[-\s]?alikes?\b|\bmistak\w*|\bconfus\w*|\bovercall\w*|\bfalse\s+positives?\b|"
            r"\b(?:my|that|the)\s+marks?\b|\bwhat\s+did\s+i\s+(?:mark|click)\b|\bM\d+\b|\bnormal\s+structures?\b",
            re.I,
        ),
    ),
    (
        "size",
        re.compile(
            r"\bhow\s+(?:big|large|small|long|wide)\b|\bsize\b|\bmeasur\w*|\bdiameter\b|\b\d+\s?mm\b|"
            r"\bmillimet\w*|\btolerance\b",
            re.I,
        ),
    ),
    (
        "why_missed",
        re.compile(
            r"\bwhy\b[^.?!]*\b(?:miss\w*|overlook\w*|not\s+(?:see|find|spot|notice)|"
            r"(?:didn'?t|couldn'?t|did\s+not|could\s+not)\s+(?:i\s+)?(?:see|find|spot|notice))\b|"
            r"\bhow\s+(?:did|could)\s+i\s+miss\b",
            re.I,
        ),
    ),
    (
        "where",
        re.compile(
            r"\bwhere\b|\blocat\w*|\bwhich\s+(?:side|zone|area|part|lung|region)\b|\bwhat\s+did\s+i\s+miss\b", re.I
        ),
    ),
    (
        "looks",
        re.compile(
            r"\blooks?\s+like\b|\brecogni[sz]\w*|\bsigns?\b|\bwhat\s+(?:should|do|must)\s+i\s+look\s+for\b|"
            r"\bhow\s+(?:do|can|would|should)\s+(?:i|you|we)\s+(?:spot|see|tell|find|identify|detect)\b|"
            r"\bappear\w*|\bidentif\w*",
            re.I,
        ),
    ),
    (
        "normal",
        re.compile(
            r"\b(?:is|was)\s+(?:it|this|that|the\s+(?:film|x-?ray|radiograph|image))\s+(?:a\s+)?normal\b|"
            r"\banything\s+(?:abnormal|wrong)\b",
            re.I,
        ),
    ),
    ("define", re.compile(r"\bwhat\s+(?:is|are|was)\b|\bwhat'?s\b|\bdefin\w*|\bmean(?:s|ing)?\b|\bexplain\b", re.I)),
)
_MARK_Q = re.compile(r"\b(?:my|that|the)\s+marks?\b|\bwhat\s+did\s+i\s+(?:mark|click)\b|\bM\d+\b", re.I)
_MISSED = ("missed_search", "missed_recognition", "missed_decision", "pattern_missed")
_MISS_KIND = {
    "missed_search": "a search miss",
    "missed_recognition": "a recognition miss",
    "missed_decision": "a decision miss",
}


def classify_question(question: str) -> str:
    """'management' | 'mimic' | 'size' | 'why_missed' | 'where' | 'looks' | 'normal' | 'define' | 'other'."""
    q = question or ""
    if _MANAGEMENT_Q.search(q):
        return "management"
    return next((name for name, rx in _INTENTS if rx.search(q)), "other")


def _sentences_within(parts: Sequence[str], max_words: int) -> str:
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if words(" ".join([*out, p])) > max_words:
            break
        out.append(p)
    return " ".join(out)


def _end(s: str) -> str:
    s = s.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _clause(s: str) -> str:
    """Lower-case first letter (keeps 'AP', 'PA'), no trailing period: for use inside a sentence."""
    s = s.strip().rstrip(".")
    return s[:1].lower() + s[1:] if s and not (len(s) > 1 and s[1].isupper()) else s


def _strip_paren(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


def _and(items: Sequence[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _tag(f: FactsFinding) -> str:
    return f"{f.id} ({f.display.lower()})"


def _outcomes(facts: DebriefFacts) -> dict[str, Outcome]:
    return {o.target: o for o in facts.outcomes}


def _result(f: FactsFinding, res: dict[str, Outcome]) -> str:
    o = res.get(f.id)
    return o.result if o else ("pattern_missed" if f.kind == "pattern" else "missed_search")


def _learner_labels(facts: DebriefFacts) -> set[str]:
    labs = {m.label for m in facts.learner.marks} | {p.label for p in facts.learner.pattern_selections}
    labs |= {o.learner_label for o in facts.outcomes if o.learner_label}
    return labs & set(vocab.labels())


def _focus(question: str, facts: DebriefFacts, asked_here: Sequence[str]) -> FactsFinding | None:
    """Finding named by id ("F2"), else by label, else the first missed one, else the first."""
    fs = facts.case.findings
    if not fs:
        return None
    ids = {x.upper() for x in re.findall(r"\bF\d+\b", question or "", re.I)}
    named = [f for f in fs if f.id.upper() in ids] or [f for f in fs if f.label in asked_here]
    if named:
        return named[0]
    res = _outcomes(facts)
    return next((f for f in fs if _result(f, res) in _MISSED), None) or next(
        (f for f in fs if _result(f, res) == "mislabeled"), fs[0]
    )


def _where_parts(f: FactsFinding, facts: DebriefFacts) -> list[str]:
    if f.kind == "pattern":
        loc = (f.relative_location or "").strip().rstrip(".")
        if f.label == "cardiomegaly":
            ctr = f" (automatic CTR {f.ctr:.2f})" if f.ctr is not None and "CTR" not in loc else ""
            if loc:
                return [f"{_tag(f)}: {loc}{ctr}. Compare the heart width with the inner chest width."]
            return [f"{_tag(f)} is a whole-film pattern: compare the heart width with the inner chest width{ctr}."]
        if loc:
            return [f"{_tag(f)} is a spread-out pattern: {loc}. Compare both lungs side to side."]
        return [f"{_tag(f)} is a whole-film pattern: judge both lungs as a whole, side to side and top to bottom."]
    loc = f.relative_location or (vocab.zone_human(f.primary_zone) if f.primary_zone else None)
    if vocab.is_volumetric(facts.case.modality):
        parts = [
            f"{_tag(f)} is in the {loc.rstrip('.')}." if loc else f"{_tag(f)} is inside its outline on the slices."
        ]
        return parts + [_end(r.text) for r in facts.spatial_relations if r.to == f.id]
    parts = [
        f"{_tag(f)} is in the {loc.rstrip('.')}." if loc else f"{_tag(f)} is inside its cyan outline on the image."
    ]
    return parts + [_end(r.text) for r in facts.spatial_relations if r.to == f.id]


def _size_parts(f: FactsFinding, facts: DebriefFacts) -> list[str]:
    """Only FACTS sizes, always in mm: the reference size, the learner's measurement and the verdict."""
    res = _outcomes(facts).get(f.id)
    parts: list[str] = []
    fact = tv.size_fact_sentence(f)
    if fact:
        parts.append(f"{_tag(f)}: {fact[0].lower()}{fact[1:]}")
    verdict = tv.size_sentence(res)
    if verdict:
        parts.append(verdict)
    elif facts.learner.measurements:
        m = facts.learner.measurements[0]
        parts.append(f"You measured {m.long_mm:g} mm on {m.mark_id}.")
    if not parts:
        parts.append(f"The reference gives no measurement for {_tag(f)}, so I cannot state a size.")
    return parts


def _unmatched_parts(facts: DebriefFacts, question: str) -> list[str]:
    """An unmatched mark (the reference labels nothing there; public datasets are not exhaustive). [] if none."""
    named = {x.upper() for x in re.findall(r"\bM\d+\b", question or "", re.I)}
    ums = sorted((o for o in facts.outcomes if o.result == "unmatched"), key=lambda o: o.target.upper() not in named)
    if not ums:
        return []
    o = ums[0]
    where = f" ({vocab.zone_human(o.zone)})" if o.zone else ""
    return [
        f"The reference does not label the spot where you placed {o.target}{where}; {tv.UNMATCHED_NOTE}. "
        "I cannot say what is there, only that the reference does not label it."
    ]


def _anatomy_parts(question: str, facts: DebriefFacts) -> list[str]:
    """Anatomy explainer for a structure named in the question (CT / MR cases only)."""
    if not vocab.is_volumetric(facts.case.modality):
        return []
    q = (question or "").lower()
    for a in cards_mod.load_anatomy().values():
        names = [a.display_name.lower(), a.anatomy.replace("_", " ")] + [vocab.zone_human(z).lower() for z in a.zones]
        names += [w.rstrip("s") for w in a.display_name.lower().split() if len(w) >= 6]  # "hemisphere", "vessel"
        if any(n in q for n in names):
            parts = [f"{a.display_name}: {_clause(a.one_liner)}."]
            if a.landmarks:
                parts.append(_end(a.landmarks[0]))
            return parts
    return []


def _signs(label: str, card: TeachingCard | None) -> list[str]:
    if not card or not card.key_signs:
        return []
    return [f"Signs of {with_article(label)}: " + "; ".join(_clause(s) for s in card.key_signs[:2]) + "."]


def _overcall_parts(
    facts: DebriefFacts, cards: dict[str, TeachingCard], zm: dict[str, Any], question: str
) -> list[str]:
    """Explain the learner's first (or named) false-positive mark or ticked pattern; [] if there is none."""
    marks = {m.id: m for m in facts.learner.marks}
    named = {x.upper() for x in re.findall(r"\bM\d+\b", question or "", re.I)}
    fps = sorted(
        (o for o in facts.outcomes if o.result == "false_positive"), key=lambda o: o.target.upper() not in named
    )
    if fps:
        o = fps[0]
        m = marks.get(o.target)
        zone = o.zone or (m.zone if m else None)
        where = f" ({vocab.zone_human(zone)})" if zone else ""
        parts = [f"Radiologists marked nothing where you placed {o.target}{where}."]
        mims = [_clause(_strip_paren(x)) for x in list((zm.get("entries") or {}).get(zone or "", []))[:3]]
        if mims:
            parts.append("Normal structures there that are often mistaken for findings: " + "; ".join(mims) + ".")
        lab = o.learner_label or (m.label if m else None)
        card = cards.get(lab or "")
        if lab and card and card.mimics:
            parts.append(f"A common look-alike of {with_article(lab)} is {_clause(_strip_paren(card.mimics[0]))}.")
        return parts
    pfs = [o for o in facts.outcomes if o.result == "pattern_false"]
    if pfs:
        lab = pfs[0].learner_label or pfs[0].target
        card = cards.get(lab)
        parts = [f"You ticked {vocab.display(lab).lower()}, but radiologists did not mark it on this film."]
        if card and card.mimics:
            parts.append(f"A common look-alike is {_clause(card.mimics[0])}.")
        return parts
    return []


def _asks_unmatched(facts: DebriefFacts, question: str) -> bool:
    named = {x.upper() for x in re.findall(r"\bM\d+\b", question or "", re.I)}
    ums = {o.target.upper() for o in facts.outcomes if o.result == "unmatched"}
    return bool(ums) and (not named or bool(named & ums))


def _mark_parts(facts: DebriefFacts, question: str) -> list[str]:
    """For a question about the learner's own (correct) mark: what it matched. [] if no such mark."""
    named = {x.upper() for x in re.findall(r"\bM\d+\b", question or "", re.I)}
    tps = [o for o in facts.outcomes if o.result == "true_positive" and o.matched]
    tps.sort(key=lambda o: o.target.upper() not in named)
    if not tps:
        return []
    o = tps[0]
    f = next((x for x in facts.case.findings if x.id == o.matched), None)
    if f is None:
        return []
    res = _outcomes(facts).get(f.id)
    if res is not None and res.result == "mislabeled" and o.learner_label:
        lab = vocab.display(o.learner_label).lower()
        return [f"{o.target} was on {_tag(f)}, the correct spot, but you labelled it {lab}."]
    return [f"{o.target} was on {_tag(f)}: radiologists marked that spot too, so your mark was correct."]


def template_answer(
    question: str,
    facts: DebriefFacts,
    cards: dict[str, TeachingCard] | None = None,
    zone_mimics: dict[str, Any] | None = None,
) -> str:
    """Deterministic, question-aware, validator-safe answer from FACTS + cards (offline / fallback path).

    The question is classified with keyword rules (classify_question): where -> relative_location of the named or
    first missed finding; looks -> the card's key signs; why_missed -> the miss-type explanation from outcomes;
    define -> the card's one-liner; mimic -> zone mimics for an overcall (else the card's mimics); normal -> whether
    radiologists marked anything; anything else -> OFFLINE_HELP. Labels radiologists did not mark are never named
    unless the learner chose them."""
    cards = cards if cards is not None else cards_mod.load_cards()
    zm = zone_mimics if zone_mimics is not None else cards_mod.load_zone_mimics()
    intent = classify_question(question)
    if intent == "management":
        return REFUSE_MANAGEMENT
    vol = vocab.is_volumetric(facts.case.modality)
    if vol:
        zm = cards_mod.all_zone_mimics(zm)
    fs = facts.case.findings
    gt = {f.label for f in fs}
    learner = _learner_labels(facts)
    mentions = label_mentions(question or "")
    asked = list(dict.fromkeys(lab for _, lab in mentions if lab is not None))
    asked_here = [lab for lab in asked if lab in gt]
    off_film = [lab for lab in asked if lab not in gt] or [t for t, lab in mentions if lab is None]
    listed = _and(sorted({x.display.lower() for x in fs})) if fs else ""
    prefix: list[str] = []
    noun = "volume" if vol else "film"
    if off_film:
        if vol:
            prefix = (
                [f"The reference does not label that on this volume; it labels {listed}."]
                if fs
                else ["The reference does not label that: it labels nothing on this volume."]
            )
        else:
            prefix = (
                [f"Radiologists did not mark that on this film; they marked {listed}."]
                if fs
                else ["Radiologists did not mark that: they marked nothing on this film."]
            )
    ids = {x.id.upper() for x in fs}
    missing_ids = sorted({x.upper() for x in re.findall(r"\bF\d+\b", question or "", re.I)} - ids)
    if missing_ids:
        have = _and([x.id for x in fs]) if fs else "no findings"
        prefix.append(f"This {noun} has {have}; there is no {_and(missing_ids)}.")
    f = _focus(question, facts, asked_here)
    same = [x for x in fs if f is not None and x.label == f.label and x.label in asked_here]
    res = _outcomes(facts)
    card = cards.get(f.label) if f else None
    nothing = "The reference labels nothing on this volume" if vol else "Radiologists marked nothing on this film"
    body: list[str]
    anatomy = _anatomy_parts(question, facts) if intent in ("define", "looks", "other", "where") and not asked else []

    if vol and intent == "size":
        body = _size_parts(f, facts) if f else [f"{nothing}, so there is no reference size to compare with."]
        body += _unmatched_parts(facts, question)[:1] if not f else []
    elif anatomy and intent in ("define", "other") and not asked_here:
        body = anatomy
    elif intent == "where":
        if len(same) > 1:
            body = [_where_parts(x, facts)[0] for x in same[:3]]
        else:
            body = _where_parts(f, facts) if f else [f"{nothing}, so there is no finding to locate."]
        if not f:
            body += _overcall_parts(facts, cards, zm, question)[:1] or _unmatched_parts(facts, question)
    elif intent == "looks":
        lab = next((x for x in asked if x in gt | learner and x in cards), None)
        if lab is not None:
            body = _signs(lab, cards[lab])
            if f and f.label == lab and f.kind == "focal":
                body += _where_parts(f, facts)[:1]
        elif f:
            body = _signs(f.label, card) + _where_parts(f, facts)[:1]
        elif vol:
            body = [
                f"{nothing}. On a lesion-free volume each slice matches the same level on the other side, "
                "so compare slice by slice before marking."
            ]
        else:
            body = [
                f"{nothing}. On a normal film each area matches the same area on the other side, "
                "so compare zone by zone before marking."
            ]
    elif intent == "why_missed":
        if f is None:
            body = [f"{nothing}, so there was nothing to miss."] + _overcall_parts(facts, cards, zm, question)[:1]
        elif _result(f, res) in ("found", "pattern_found"):
            who = "the reference labels" if vol else "radiologists marked"
            body = [f"You did not miss anything {who}: you found every finding on this {noun}."]
            body += _overcall_parts(facts, cards, zm, question)[:1]
        else:
            r = _result(f, res)
            o = res.get(f.id)
            lead = f"{_tag(f)} was {_MISS_KIND[r]}." if r in _MISS_KIND else ""
            if vol:
                body = [lead, tv.why(facts, f, o, r, card, o.learner_label if o else None, "full", cards)]
            else:
                body = [lead, why_sentence(f, r, card, o.learner_label if o else None, cards)]
    elif intent == "mimic":
        body = _overcall_parts(facts, cards, zm, question)
        if not body and not re.search(r"\bmimic\w*|\blook[-\s]?alikes?\b", question or "", re.I):
            if _MARK_Q.search(question or ""):
                body = _unmatched_parts(facts, question) if _asks_unmatched(facts, question) else []
                body = body or _mark_parts(facts, question) or [f"You did not place any marks on this {noun}."]
        if not body:
            body = ["A mimic is a normal structure that can look like a finding."]
            if f and card and card.mimics:
                looks = "; ".join(_clause(_strip_paren(x)) for x in card.mimics[:2])
                body.append(f"Look-alikes of {with_article(f.label)}: {looks}.")
            else:
                body.append("Common ones are vessels seen end-on, rib crossings, the nipple shadow and skin folds.")
    elif intent == "normal":
        if f is None:
            body = [f"Yes: {nothing[0].lower()}{nothing[1:]}, so it is a normal study."]
            body += _overcall_parts(facts, cards, zm, question)[:1] or _unmatched_parts(facts, question)
        else:
            body = [f"No: {'the reference labels' if vol else 'radiologists marked'} {listed}."]
            body += _where_parts(f, facts)[:1]
    elif intent == "define":
        lab = next((x for x in asked if x in gt | learner and x in cards), None)
        if lab is not None:
            c = cards[lab]
            body = [f"{c.display_name}: {_clause(c.one_liner)}."]
            if f and f.label == lab:
                body += _where_parts(f, facts)[:1]
            elif f and card:
                body.append(f"{f.display}: {_clause(card.one_liner)}.")
        elif anatomy:
            body = anatomy
        elif f and card:
            body = [f"{f.id} is {with_article(f.label)}: {_clause(card.one_liner)}."]
        elif prefix:
            body = ["I can only explain the labels that are part of this case."]
        else:
            body = [f"{nothing}; it is a normal study."] if not fs else [OFFLINE_HELP]
    elif asked_here and f is not None:
        who = "the reference labels" if vol else "radiologists marked"
        if len(same) > 1:
            body = [f"Yes: {who} {len(same)} findings with that label on this {noun}."]
            body += [_where_parts(x, facts)[0] for x in same[:3]]
        else:
            body = [f"Yes: {who} {with_article(f.label)} on this {noun}."] + _where_parts(f, facts)[:1]
        body += _signs(f.label, card)
    elif prefix:
        body = _where_parts(f, facts)[:1] if f else []
    else:
        body = [OFFLINE_HELP]
    return _sentences_within(prefix + body, ASK_MAX_WORDS)


def _user_text(question: str, facts: DebriefFacts, previous: Sequence[dict[str, Any]]) -> str:
    lines = ["FACTS:\n" + facts_json(facts)]
    for qa in previous or []:
        lines.append(f"EARLIER QUESTION: {qa.get('question', '')}\nEARLIER ANSWER: {qa.get('answer', '')}")
    lines.append(f"QUESTION: {question}")
    return "\n\n".join(lines)


def ask(
    question: str,
    facts: DebriefFacts,
    case: Case,
    *,
    previous: Sequence[dict[str, Any]] | None = None,
    offline: bool | None = None,
    client: Any | None = None,
    images: dict[str, bytes] | None = None,
    data_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return {"answer", "source": "live"|"template", "validator", "latency_ms", "model", "error", "input_tokens",
    "output_tokens", "cache_read_tokens", "cost_usd"}. Never raises. `error` is None for live answers, else the
    client.fallback_error code (offline, credits_depleted, rate_limited, budget_exceeded, timeout, ...)."""
    out = _ask(
        question, facts, case, previous=previous, offline=offline, client=client, images=images, data_root=data_root
    )
    try:
        analytics.report_ask()
    except Exception:  # noqa: BLE001
        log.exception("analytics report failed")
    return out


def _ask(
    question: str,
    facts: DebriefFacts,
    case: Case,
    *,
    previous: Sequence[dict[str, Any]] | None,
    offline: bool | None,
    client: Any | None,
    images: dict[str, bytes] | None,
    data_root: Path | str | None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    settings = get_settings()
    offline = settings.offline if offline is None else offline
    cards = cards_mod.load_cards()
    zm = cards_mod.load_zone_mimics()
    model = getattr(client, "model", None) or settings.blindspot_model_debrief

    usage: dict[str, Any] = {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None, "cost_usd": None}

    def done(answer: str, source: str, v: dict[str, Any], mdl: str | None, error: str | None = None) -> dict[str, Any]:
        return {
            "answer": answer,
            "source": source,
            "validator": v,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "model": mdl,
            "error": error,
            **usage,
        }

    def template(reason: str, errors: list[str] | None = None) -> dict[str, Any]:
        ans = template_answer(question, facts, cards, zm)
        v = validate_ask(ans, facts, cards, zone_mimics=zm).to_dict()
        vd = {**v, "fallback_reason": reason, "live_errors": errors or []}
        return done(ans, "template", vd, None, fallback_error(reason))

    try:
        if offline:
            return template("offline")
        tc = as_tutor_client(client, model)
        if tc is None:
            if not settings.anthropic_api_key:
                return template("no_api_key")
            tc = AnthropicTutorClient(model=model)
        if images is None and data_root is not None:
            try:
                from backend.app.tutor.render import render_images

                images = render_images(case, facts, [], data_root)
            except Exception:  # noqa: BLE001
                images = None
        system = system_blocks(load_prompt("ask_system").text, cards_mod.all_cards_text())
        messages = [
            {"role": "user", "content": user_content(ordered(images), _user_text(question, facts, previous or []))}
        ]
        try:
            resp = guarded_complete(tc, system=system, messages=messages, schema=ASK_SCHEMA, max_tokens=ASK_MAX_TOKENS)
        except LiveCallError as e:
            return template(e.reason)
        usage.update(
            input_tokens=(resp.input_tokens or 0)
            + (resp.cache_read_input_tokens or 0)
            + (resp.cache_creation_input_tokens or 0),
            output_tokens=resp.output_tokens or 0,
            cache_read_tokens=resp.cache_read_input_tokens or 0,
            cost_usd=resp.cost_usd,
        )
        try:
            answer = str(json.loads(resp.text)["answer"]).strip()
        except Exception:  # noqa: BLE001
            return template("bad_json")
        v = validate_ask(answer, facts, cards, zone_mimics=zm)
        if not v.ok:
            return template("validator_failed", v.errors)
        return done(answer, "live", v.to_dict(), resp.model or model)
    except Exception:  # noqa: BLE001
        log.exception("ask failed")
        return template("internal_error")


def answer_question(question: str, facts: DebriefFacts, case: Case, *, remaining: int, **kw: Any) -> AskResponse:
    """Convenience wrapper returning the API model."""
    r = ask(question, facts, case, **kw)
    return AskResponse(answer=r["answer"], remaining=remaining, source=r["source"])
