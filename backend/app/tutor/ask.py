"""Ask the tutor (SPEC §8.9): up to 3 follow-up questions per case, same FACTS and images.

Live answers are validated (R3 laterality, R5 labels, R6 banned content, ≤ 90 words); any failure, offline mode,
or API error returns a deterministic template answer built from FACTS + cards.
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
from backend.app.tutor import cards as cards_mod
from backend.app.tutor import vocab
from backend.app.tutor.client import (
    ASK_MAX_TOKENS,
    ASK_SCHEMA,
    AnthropicTutorClient,
    LiveCallError,
    as_tutor_client,
    system_blocks,
    user_content,
)
from backend.app.tutor.facts import facts_json
from backend.app.tutor.prompts import load_prompt
from backend.app.tutor.render import ordered
from backend.app.tutor.templates import with_article
from backend.app.tutor.validator import ASK_MAX_WORDS, label_mentions, validate_ask, words
from shared.contracts import AskResponse, Case, DebriefFacts, TeachingCard

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


def template_answer(question: str, facts: DebriefFacts, cards: dict[str, TeachingCard] | None = None) -> str:
    """Deterministic, validator-safe answer from FACTS + cards."""
    cards = cards if cards is not None else cards_mod.load_cards()
    if _MANAGEMENT_Q.search(question or ""):
        return REFUSE_MANAGEMENT
    gt = {f.label for f in facts.case.findings}
    asked = [lab for _, lab in label_mentions(question or "") if lab is not None]
    not_here = [lab for lab in asked if lab not in gt]
    res = {o.target: o.result for o in facts.outcomes}
    if not facts.case.findings:
        parts = ["Radiologists marked nothing on this film; it is a normal study."]
        if not_here:
            parts.insert(0, "Radiologists did not mark that on this film.")
        fps = [o for o in facts.outcomes if o.result == "false_positive"]
        if fps:
            parts.append(
                "Normal structures such as vessels seen end-on, rib crossings and skin folds are often "
                "mistaken for findings."
            )
        parts.append("Compare each area with the same area on the other side before marking.")
        return _sentences_within(parts, ASK_MAX_WORDS)
    asked_here = [lab for lab in asked if lab in gt]
    order = sorted(
        facts.case.findings,
        key=lambda f: (f.label not in asked_here, not str(res.get(f.id, "")).startswith("missed"), f.id),
    )
    f = order[0]
    card = cards.get(f.label)
    parts = []
    if not_here:
        listed = ", ".join(sorted({x.display.lower() for x in facts.case.findings}))
        parts.append(f"Radiologists did not mark that on this film; they marked {listed}.")
    loc = f.relative_location or (vocab.zone_human(f.primary_zone) if f.primary_zone else None)
    parts.append(f"{f.id} is {with_article(f.label)}" + (f", in the {loc}." if loc and f.kind == "focal" else "."))
    if card:
        parts.append(_end(f"{f.display}: {card.one_liner[:1].lower()}{card.one_liner[1:]}"))
        if card.key_signs:
            parts.append(_end("Look for " + card.key_signs[0][:1].lower() + card.key_signs[0][1:]))
        parts.append(_end(card.search_tip))
    return _sentences_within(parts, ASK_MAX_WORDS)


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
    """Return {"answer", "source": "live"|"template", "validator", "latency_ms", "model"}. Never raises."""
    t0 = time.perf_counter()
    settings = get_settings()
    offline = settings.offline if offline is None else offline
    cards = cards_mod.load_cards()
    zm = cards_mod.load_zone_mimics()
    model = getattr(client, "model", None) or settings.blindspot_model_debrief

    def done(answer: str, source: str, v: dict[str, Any], mdl: str | None) -> dict[str, Any]:
        return {
            "answer": answer,
            "source": source,
            "validator": v,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "model": mdl,
        }

    def template(reason: str, errors: list[str] | None = None) -> dict[str, Any]:
        ans = template_answer(question, facts, cards)
        v = validate_ask(ans, facts, cards, zone_mimics=zm).to_dict()
        return done(ans, "template", {**v, "fallback_reason": reason, "live_errors": errors or []}, None)

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
            resp = tc.complete(system=system, messages=messages, schema=ASK_SCHEMA, max_tokens=ASK_MAX_TOKENS)
        except LiveCallError as e:
            return template(f"live_{e.kind}")
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
