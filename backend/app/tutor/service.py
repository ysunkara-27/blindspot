"""Debrief orchestration (SPEC §8.5–8.7).

cache hit (re-validated) → offline? template → live call → validator → one regeneration with "Fix these
problems: …" → template. Never raises; every path returns a validated debrief or, at worst, the template.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.app.settings import get_settings
from backend.app.tutor import cards as cards_mod
from backend.app.tutor import vocab
from backend.app.tutor.cache import cache_key_for_facts
from backend.app.tutor.client import (
    DEBRIEF_MAX_TOKENS,
    AnthropicTutorClient,
    LiveCallError,
    TutorClient,
    as_tutor_client,
    debrief_schema,
    system_blocks,
    user_content,
)
from backend.app.tutor.facts import facts_json
from backend.app.tutor.prompts import load_prompt
from backend.app.tutor.render import ordered, primary_target, render_images
from backend.app.tutor.templates import template_debrief
from backend.app.tutor.validator import validate
from shared.contracts import AttemptSubmit, Case, DebriefFacts, DebriefOutput

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


def user_text(facts: DebriefFacts, case: Case, has_images: bool) -> str:
    parts = []
    if has_images:
        _, _, target = primary_target(case, facts, [])
        around = f"around {target.short_id}" if target is not None else "around the learner's mark"
        parts.append(
            "IMAGES: 1 = the whole film (cyan outlines = radiologist findings F#, amber circles = learner marks M#); "
            f"2 = close-up {around} without outlines; 3 = the same close-up with thin cyan outlines."
        )
    parts.append("FACTS:\n" + facts_json(facts))
    return "\n".join(parts)


def build_request(facts: DebriefFacts, case: Case, images: dict[str, bytes] | None) -> tuple[list, list]:
    system = system_blocks(load_prompt("debrief_system").text, cards_mod.all_cards_text())
    imgs = ordered(images)
    messages = [{"role": "user", "content": user_content(imgs, user_text(facts, case, bool(imgs)))}]
    return system, messages


def fix_messages(messages: list[dict], previous_text: str, errors: list[str]) -> list[dict]:
    fix = "Fix these problems: " + "; ".join(errors) + ". Return the full corrected JSON."
    return [*messages, {"role": "assistant", "content": previous_text}, {"role": "user", "content": fix}]


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
) -> dict[str, Any]:
    """Return {"debrief", "source", "provenance", "validator", "latency_ms", "model", "prompt_version",
    "cache_key", "input_tokens", "output_tokens"}. The caller persists it (debriefs table)."""
    t0 = time.perf_counter()
    settings = get_settings()
    offline = settings.offline if offline is None else offline
    model = getattr(client, "model", None) or settings.blindspot_model_debrief
    cards = cards_mod.load_cards()
    zm = cards_mod.load_zone_mimics()
    cfg = vocab.validator_cfg()
    pv = prompt_version()
    key = cache_key_for_facts(facts, model, pv)
    provenance = cards_mod.lowest_provenance(
        facts.teaching_cards, cards, include_zone_mimics=any(o.result == "false_positive" for o in facts.outcomes)
    )
    attempts: list[dict[str, Any]] = []
    tokens_in = tokens_out = 0
    used_live = False

    def template(reason: str) -> dict[str, Any]:
        try:
            out = template_debrief(facts, cards, zm, cfg)
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
        return _result(out, "template", provenance, vd, t0, None, pv, key, toks)

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
        system, messages = build_request(facts, case, images)
        schema = debrief_schema()
        for attempt in (1, 2):
            try:
                resp = tc.complete(system=system, messages=messages, schema=schema, max_tokens=DEBRIEF_MAX_TOKENS)
            except LiveCallError as e:
                attempts.append({"attempt": attempt, "ok": False, "errors": [f"live call failed: {e.kind}"]})
                return template(f"live_{e.kind}")
            used_live = True
            tokens_in += (
                (resp.input_tokens or 0) + (resp.cache_read_input_tokens or 0) + (resp.cache_creation_input_tokens or 0)
            )
            tokens_out += resp.output_tokens or 0
            try:
                out = _parse(resp.text)
                v = validate(out, facts, cards, cfg, zone_mimics=zm)
                errors = v.errors
            except Exception as e:  # noqa: BLE001 — malformed JSON or schema mismatch
                out, errors = None, [f"R0 schema: {str(e).splitlines()[0][:200]}"]
            attempts.append(
                {
                    "attempt": attempt,
                    "ok": not errors,
                    "errors": errors,
                    "latency_ms": round(resp.latency_ms, 1),
                    "cache_read_input_tokens": resp.cache_read_input_tokens,
                }
            )
            if out is not None and not errors:
                vd = {
                    "ok": True,
                    "errors": [],
                    "n_errors": 0,
                    "attempts": attempts,
                    "first_try_ok": attempts[0]["ok"],
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
                )
            if attempt == 1:
                messages = fix_messages(messages, resp.text, errors)
        return template("validator_failed")
    except Exception as e:  # noqa: BLE001 — never raise into the request path
        log.exception("generate_debrief failed")
        attempts.append({"attempt": len(attempts) + 1, "ok": False, "errors": [f"internal error: {type(e).__name__}"]})
        return template("internal_error")
