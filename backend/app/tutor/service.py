"""Debrief orchestration (SPEC §8.5–8.7).

cache hit (re-validated) → offline? template → guard (paused / over budget? template) → live call → validator → one
regeneration with "Fix these problems: …" → template. Never raises; every path returns a validated debrief or, at
worst, the template. Every live call goes through tutor.guard.guarded_complete (pause state, budget, spend).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.app.settings import get_settings
from backend.app.tutor import analytics, vocab
from backend.app.tutor import cards as cards_mod
from backend.app.tutor.cache import cache_key_for_facts
from backend.app.tutor.client import (
    AnthropicTutorClient,
    LiveCallError,
    TutorClient,
    as_tutor_client,
    debrief_max_tokens,
    debrief_schema,
    fallback_error,
    system_blocks,
    user_content,
)
from backend.app.tutor.facts import facts_json
from backend.app.tutor.guard import guarded_complete
from backend.app.tutor.prompts import load_prompt
from backend.app.tutor.render import ordered, primary_target, render_images
from backend.app.tutor.templates import template_debrief
from backend.app.tutor.validator import total_word_limit, total_words, validate
from shared.contracts import AttemptSubmit, Case, DebriefFacts, DebriefOutput, TeachingCard

log = logging.getLogger("blindspot.tutor")


def prompt_version() -> str:
    """Prompt file version + hash of the cached cards block (card text, not review metadata)."""
    return f"{load_prompt('debrief_system').version}+{cards_mod.content_hash()[:8]}"


def _data_root() -> Path:
    try:
        from backend.app.cases import processed_root

        return processed_root()
    except Exception:  # noqa: BLE001
        return get_settings().processed_dir


def focus_line(facts: DebriefFacts, focus_label: str | None) -> str | None:
    """Drill sessions: one line naming the drill label, only when this film has a finding with that label.
    FACTS is unchanged (it still lists every finding); the line only tells the tutor what to lead with."""
    if not focus_label or not any(f.label == focus_label for f in facts.case.findings):
        return None
    ids = ", ".join(f.id for f in facts.case.findings if f.label == focus_label)
    return (
        f"DRILL FOCUS: {focus_label} ({ids}). The learner is drilling this finding type: lead the headline with how "
        "they did on it. FACTS still lists every finding; include every one of them as usual."
    )


def user_text(facts: DebriefFacts, case: Case, has_images: bool, focus_label: str | None = None) -> str:
    parts = []
    if has_images:
        _, _, target = primary_target(case, facts, [])
        around = f"around {target.short_id}" if target is not None else "around the learner's mark"
        parts.append(
            "IMAGES: 1 = the whole film (cyan outlines = radiologist findings F#, amber circles = learner marks M#); "
            f"2 = close-up {around} without outlines; 3 = the same close-up with thin cyan outlines."
        )
    focus = focus_line(facts, focus_label)
    if focus:
        parts.append(focus)
    parts.append("FACTS:\n" + facts_json(facts))
    return "\n".join(parts)


def build_request(
    facts: DebriefFacts, case: Case, images: dict[str, bytes] | None, focus_label: str | None = None
) -> tuple[list, list]:
    system = system_blocks(load_prompt("debrief_system").text, cards_mod.all_cards_text())
    imgs = ordered(images)
    messages = [{"role": "user", "content": user_content(imgs, user_text(facts, case, bool(imgs), focus_label))}]
    return system, messages


LENGTH_TARGET_WORDS = 110  # what the prompt asks for; the validator cap stays total_max_words (160)
_R9 = re.compile(r"^R9 ")
_R7_TOTAL = re.compile(r"R7: all text fields together have (\d+) words; maximum (\d+)")
_R7_HEADLINE = re.compile(r"R7: headline has (\d+) words; maximum (\d+)")


def fix_messages(messages: list[dict], previous_text: str, errors: list[str]) -> list[dict]:
    """Regeneration turn: the validator errors plus, for length failures, the exact count and a concrete target."""
    parts = ["Fix these problems: " + "; ".join(errors) + "."]
    total = next((m for m in map(_R7_TOTAL.search, errors) if m), None)
    if total:
        have, cap = int(total[1]), int(total[2])
        target = LENGTH_TARGET_WORDS if cap <= 160 else round(0.7 * cap)
        parts.append(
            f"Your text fields total {have} words; the hard limit is {cap}. Rewrite to at most {target} words in "
            f"total (cut at least {max(1, have - target)} words): follow the LENGTH BUDGET, shorten every "
            "where_to_look and why, and keep at most one what_it_looks_like item per finding."
        )
    head = next((m for m in map(_R7_HEADLINE.search, errors) if m), None)
    if head:
        parts.append(f"The headline has {head[1]} words; use at most 10.")
    if any(e.startswith("R3") for e in errors):
        parts.append(
            'Use "right" and "left" only for the patient\'s side, exactly as FACTS gives it; if you meant "correct", '
            'write "correct" (not "right spot" or "got it right").'
        )
    if any(_R9.match(e) for e in errors):
        parts.append(
            "Every finding, including the ones the learner found, needs at least one what_it_looks_like item (a key "
            "sign from its teaching card) and a why that is a full sentence of at least 6 words."
        )
    parts.append("Keep every finding_id, result, mark_id and fact_id unchanged. Return the full corrected JSON.")
    fix = " ".join(parts)
    return [*messages, {"role": "assistant", "content": previous_text}, {"role": "user", "content": fix}]


def _length_only(errors: list[str]) -> bool:
    return bool(errors) and all(_R7_TOTAL.search(e) for e in errors)


def trim_to_fit(
    out: DebriefOutput,
    facts: DebriefFacts,
    cards: dict[str, TeachingCard],
    cfg: dict[str, Any],
    zone_mimics: dict[str, Any],
) -> DebriefOutput | None:
    """Length-only failure: delete whole optional list items (never edit a word) until R7 holds, then re-validate.

    Order: extra possible_mimics -> extra what_it_looks_like items (one sign per finding always stays: validator
    R9) -> calibration_note. Returns None if it still does not fit or does not validate."""
    steps = (
        lambda o: o.model_copy(
            update={"overcalls": [x.model_copy(update={"possible_mimics": x.possible_mimics[:1]}) for x in o.overcalls]}
        ),
        lambda o: o.model_copy(
            update={
                "findings": [x.model_copy(update={"what_it_looks_like": x.what_it_looks_like[:1]}) for x in o.findings]
            }
        ),
        lambda o: o.model_copy(update={"calibration_note": ""}),
    )
    limit = total_word_limit(facts, cfg)
    cur = out
    for step in steps:
        cur = step(cur)
        if total_words(cur) <= limit:
            return cur if validate(cur, facts, cards, cfg, zone_mimics=zone_mimics).ok else None
    return None


def _parse(text: str) -> DebriefOutput:
    return DebriefOutput.model_validate(json.loads(text))


def _row_output(row: dict[str, Any]) -> DebriefOutput | None:
    raw = row.get("output_json", row.get("debrief", row.get("output")))
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = json.loads(raw)
    return DebriefOutput.model_validate(raw)


def _result(
    out: DebriefOutput | None,
    source: str,
    provenance: str,
    validator: dict,
    t0: float,
    model: str | None,
    pv: str,
    key: str,
    tokens: tuple[int | None, int | None],
    error: str | None = None,
    cache_read_tokens: int | None = None,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    return {
        "debrief": out,
        "source": source,
        "provenance": provenance,
        "validator": validator,
        "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        "model": model,
        "prompt_version": pv,
        "cache_key": key,
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "cache_read_tokens": cache_read_tokens,
        "cost_usd": cost_usd,  # estimated (tutor.spend), None when no live call was made
        "error": error,  # None unless source == "template" (then offline | rate_limited | timeout | ...)
    }


def generate_debrief(
    facts: DebriefFacts,
    case: Case,
    *,
    attempt_id: str | None = None,
    submit: AttemptSubmit | None = None,
    offline: bool | None = None,
    cache_get: Callable[[str], dict[str, Any] | None] | None = None,
    client: Any | None = None,
    data_root: Path | str | None = None,
    images: dict[str, bytes] | None = None,
    focus_label: str | None = None,
) -> dict[str, Any]:
    """Return {"debrief", "source", "provenance", "validator", "latency_ms", "model", "prompt_version",
    "cache_key", "input_tokens", "output_tokens", "cache_read_tokens", "cost_usd", "error"}. The caller persists it
    (debriefs table).

    `focus_label`: the drill label of a drill session. FACTS still lists every finding (truth); the prompt and the
    template headline may lead with the focus label. It is part of the cache key only when the film has that label.

    `error` is None for live/cache results; for source == "template" it is the short code from
    client.fallback_error(validator["fallback_reason"]): offline | credits_depleted | rate_limited |
    budget_exceeded | unavailable | auth | validator_failed | timeout | internal_error (PROGRESS.md TUTOR ERRORS)."""
    out = _generate_debrief(
        facts,
        case,
        attempt_id=attempt_id,
        submit=submit,
        offline=offline,
        cache_get=cache_get,
        client=client,
        data_root=data_root,
        images=images,
        focus_label=focus_label,
    )
    try:
        analytics.report_debrief(out)
    except Exception:  # noqa: BLE001
        log.exception("analytics report failed")
    return out


def _generate_debrief(
    facts: DebriefFacts,
    case: Case,
    *,
    attempt_id: str | None,
    submit: AttemptSubmit | None,
    offline: bool | None,
    cache_get: Callable[[str], dict[str, Any] | None] | None,
    client: Any | None,
    data_root: Path | str | None,
    images: dict[str, bytes] | None,
    focus_label: str | None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    settings = get_settings()
    offline = settings.offline if offline is None else offline
    model = getattr(client, "model", None) or settings.blindspot_model_debrief
    cards = cards_mod.load_cards()
    zm = cards_mod.load_zone_mimics()
    cfg = vocab.validator_cfg()
    pv = prompt_version()
    if not focus_line(facts, focus_label):
        focus_label = None  # a drill film without the drill label (e.g. a normal) is an ordinary debrief
    key = cache_key_for_facts(facts, model, pv, focus_label=focus_label)
    provenance = cards_mod.lowest_provenance(
        facts.teaching_cards, cards, include_zone_mimics=any(o.result == "false_positive" for o in facts.outcomes)
    )
    attempts: list[dict[str, Any]] = []
    tokens_in = tokens_out = cache_read = 0
    cost_usd = 0.0
    used_live = False

    def template(reason: str) -> dict[str, Any]:
        try:
            out = template_debrief(facts, cards, zm, cfg, focus_label=focus_label)
        except Exception as e:  # noqa: BLE001 — a template bug must not crash the request
            log.exception("template_debrief failed")
            return _result(
                None,
                "template",
                provenance,
                {"ok": False, "errors": [f"template error: {e}"], "fallback_reason": reason, "attempts": attempts},
                t0,
                None,
                pv,
                key,
                (None, None),
                fallback_error(reason),
            )
        v = validate(out, facts, cards, cfg, zone_mimics=zm)
        vd = {
            **v.to_dict(),
            "fallback_reason": reason,
            "attempts": attempts,
            "first_try_ok": attempts[0]["ok"] if attempts else None,
            "regenerated": len(attempts) > 1,
        }
        toks = (tokens_in or None, tokens_out or None) if used_live else (None, None)
        return _result(
            out,
            "template",
            provenance,
            vd,
            t0,
            None,
            pv,
            key,
            toks,
            fallback_error(reason),
            cache_read_tokens=cache_read if used_live else None,
            cost_usd=round(cost_usd, 6) if used_live else None,
        )

    try:
        # 1. cache (only live-generated rows; always re-validated against the current FACTS)
        if cache_get is not None:
            try:
                row = cache_get(key)
            except Exception:  # noqa: BLE001
                log.exception("cache_get failed")
                row = None
            if row and row.get("source", "live") != "template":
                out = _row_output(row)
                if out is not None:
                    v = validate(out, facts, cards, cfg, zone_mimics=zm)
                    if v.ok:
                        return _result(
                            out,
                            "cache",
                            provenance,
                            {**v.to_dict(), "cached": True},
                            t0,
                            row.get("model") or model,
                            pv,
                            key,
                            (None, None),
                        )
                    log.warning("cached debrief %s failed re-validation: %s", key[:12], v.errors)

        # 2. offline → template
        if offline:
            return template("offline")

        # 3. live
        tc: TutorClient | None = as_tutor_client(client, model)
        if tc is None:
            if not settings.anthropic_api_key:
                return template("no_api_key")
            tc = AnthropicTutorClient(model=model)
        if images is None:
            try:
                marks = submit.marks if submit is not None else []
                images = render_images(case, facts, marks, Path(data_root) if data_root else _data_root())
            except Exception as e:  # noqa: BLE001 — text-only debrief is still grounded in FACTS
                log.warning("render_images failed for %s: %s", case.case_id, e)
                images = None
        system, messages = build_request(facts, case, images, focus_label)
        schema = debrief_schema()
        max_tokens = debrief_max_tokens(len(facts.case.findings))
        for attempt in (1, 2):
            try:
                resp = guarded_complete(tc, system=system, messages=messages, schema=schema, max_tokens=max_tokens)
            except LiveCallError as e:
                what = "live call skipped" if e.paused else "live call failed"
                attempts.append({"attempt": attempt, "ok": False, "errors": [f"{what}: {e.kind}"]})
                return template(e.reason)
            used_live = True
            tokens_in += (
                (resp.input_tokens or 0) + (resp.cache_read_input_tokens or 0) + (resp.cache_creation_input_tokens or 0)
            )
            tokens_out += resp.output_tokens or 0
            cache_read += resp.cache_read_input_tokens or 0
            cost_usd += resp.cost_usd or 0.0
            try:
                out = _parse(resp.text)
                v = validate(out, facts, cards, cfg, zone_mimics=zm)
                errors = v.errors
            except Exception as e:  # noqa: BLE001 — malformed JSON or schema mismatch
                out, errors = None, [f"R0 schema: {str(e).splitlines()[0][:200]}"]
            trimmed = None
            if out is not None and _length_only(errors):
                trimmed = trim_to_fit(out, facts, cards, cfg, zm)
            attempts.append(
                {
                    "attempt": attempt,
                    "ok": not errors,
                    "errors": errors,
                    "trimmed": trimmed is not None,
                    "words": total_words(out) if out is not None else None,
                    "latency_ms": round(resp.latency_ms, 1),
                    "output_tokens": resp.output_tokens,
                    "cache_read_input_tokens": resp.cache_read_input_tokens,
                }
            )
            if trimmed is not None:
                out, errors = trimmed, []
            if out is not None and not errors:
                vd = {
                    "ok": True,
                    "errors": [],
                    "n_errors": 0,
                    "attempts": attempts,
                    "first_try_ok": attempts[0]["ok"],  # the raw model output, before any trim
                    "trimmed": attempts[-1]["trimmed"],
                    "regenerated": attempt > 1,
                }
                return _result(
                    out,
                    "live",
                    provenance,
                    vd,
                    t0,
                    resp.model or model,
                    pv,
                    key,
                    (tokens_in or None, tokens_out or None),
                    cache_read_tokens=cache_read,
                    cost_usd=round(cost_usd, 6),
                )
            if attempt == 1:
                messages = fix_messages(messages, resp.text, errors)
        return template("validator_failed")
    except Exception as e:  # noqa: BLE001 — never raise into the request path
        log.exception("generate_debrief failed")
        attempts.append({"attempt": len(attempts) + 1, "ok": False, "errors": [f"internal error: {type(e).__name__}"]})
        return template("internal_error")
