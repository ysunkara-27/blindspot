"""Thin, failure-tolerant bridge to backend/app/tutor (owned by tutor-prompt-engineer).

Every call imports lazily and falls back deterministically if the tutor module is missing or raises.
The Anthropic client is never created here: the tutor decides (offline → never). Tests inject a mock via
`set_client()` or monkeypatch these functions.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from backend.app import config
from backend.app.search.coverage import review_coverage
from backend.app.search.dwell import dwell_samples
from shared.contracts import (
    AttemptSubmit,
    Case,
    DebriefFacts,
    DebriefOutput,
    FactsSearch,
    Mark,
    Outcome,
    SpatialRelation,
    TeachingCard,
    TelemetryEvent,
)

log = logging.getLogger("blindspot.tutor_bridge")
_client: Any | None = None


def set_client(client: Any | None) -> None:
    """Inject an Anthropic-like client (tests pass a mock)."""
    global _client
    _client = client


def _mod(name: str) -> Any | None:
    try:
        return importlib.import_module(f"backend.app.tutor.{name}")
    except Exception as e:  # noqa: BLE001 — tutor not landed or broken → fallback
        log.debug("tutor.%s unavailable: %s", name, e)
        return None


def available() -> bool:
    return _mod("facts") is not None and _mod("service") is not None


# ------------------------------------------------------------------ facts + debrief
def build_facts(
    *,
    case: Case,
    submit: AttemptSubmit,
    outcomes: list[Outcome],
    spatial_relations: list[SpatialRelation],
    search: FactsSearch,
    mark_zones: dict[str, str | None],
    level: str,
    history: dict[str, Any],
) -> DebriefFacts | None:
    m = _mod("facts")
    if m is None or not hasattr(m, "build_facts"):
        return None
    try:
        return m.build_facts(
            case=case,
            submit=submit,
            outcomes=outcomes,
            spatial_relations=spatial_relations,
            search=search,
            mark_zones=mark_zones,
            level=level,
            history=history,
        )
    except Exception:  # noqa: BLE001
        log.exception("tutor.facts.build_facts failed")
        return None


def generate_debrief(
    facts: DebriefFacts,
    case: Case,
    *,
    attempt_id: str,
    submit: AttemptSubmit,
    offline: bool,
    cache_get: Any,
    focus_label: str | None = None,
) -> dict[str, Any] | None:
    """`focus_label`: the drill label of a drill session (FACTS still lists every finding; the tutor may lead with
    the focus label)."""
    m = _mod("service")
    if m is None or not hasattr(m, "generate_debrief"):
        return None
    extra = {"focus_label": focus_label} if focus_label else {}  # only drill sessions pass it
    try:
        out = m.generate_debrief(
            facts,
            case,
            attempt_id=attempt_id,
            submit=submit,
            offline=offline,
            cache_get=cache_get,
            client=_client,
            **extra,
        )
    except Exception:  # noqa: BLE001
        log.exception("tutor.service.generate_debrief failed")
        return None
    if not isinstance(out, dict) or out.get("debrief") is None:
        return None
    d = out["debrief"]
    out["debrief"] = d if isinstance(d, DebriefOutput) else DebriefOutput.model_validate(d)
    out.setdefault("error", fallback_error(out))
    return out


# validator.fallback_reason (tutor.service) → DebriefResponse.error, so the UI can say why it got a template.
_FALLBACK_ERRORS = {"live_rate_limited": "rate_limited"}


def fallback_error(out: dict[str, Any]) -> str | None:
    """'rate_limited' when the tutor client's per-minute cap turned a live call into a template; else None."""
    if out.get("source") != "template":
        return None
    v = out.get("validator") or {}
    reason = v.get("fallback_reason") if isinstance(v, dict) else None
    return _FALLBACK_ERRORS.get(reason) if isinstance(reason, str) else None


# ------------------------------------------------------------------ cards
def load_cards() -> dict[str, TeachingCard]:
    m = _mod("cards")
    if m is not None and hasattr(m, "load_cards"):
        try:
            return dict(m.load_cards(config.cards_dir()))
        except Exception:  # noqa: BLE001
            log.exception("tutor.cards.load_cards failed")
    out: dict[str, TeachingCard] = {}
    d: Path = config.cards_dir()
    if d.exists():
        for p in sorted(d.glob("*.yaml")):
            try:
                c = TeachingCard.model_validate(yaml.safe_load(p.read_text()))
                out[c.label] = c
            except Exception:  # noqa: BLE001
                continue
    return out


def lowest_provenance(labels: list[str]) -> str | None:
    m = _mod("cards")
    if m is not None and hasattr(m, "lowest_provenance"):
        try:
            return m.lowest_provenance(labels, load_cards())
        except Exception:  # noqa: BLE001
            pass
    order = ["ai_draft", "student_reviewed", "radiologist_reviewed"]
    cards = load_cards()
    statuses = [cards[lab].review.status for lab in labels if lab in cards]
    return min(statuses, key=order.index) if statuses else "ai_draft"


# ------------------------------------------------------------------ hints
FALLBACK_ALL_VISITED = "Compare each region with the same region on the other side."
FALLBACK_MAX_AREAS = 3
FALLBACK_NAMES = {"retrocardiac": "area behind the heart"}


def fallback_hint(
    level: int, case: Case, marks: list[Mark], telemetry: list[TelemetryEvent], zones: dict[str, np.ndarray]
) -> str:
    """Deterministic hint when the tutor module is unavailable: the H1 search cue at EVERY level. It depends only on
    the learner's search (unvisited review areas), never on findings, so it cannot reveal whether the film is normal
    (QA #8; the tutor's symmetric H2/H3 templates live in backend/app/tutor/hints.py). Same wording as the tutor's
    H1: at most FALLBACK_MAX_AREAS areas, the least-dwelt unvisited ones, in the fixed order of config review_areas."""
    sc = config.scoring()
    cov = review_coverage(
        dwell_samples(telemetry, sc["dwell"]), zones, config.review_area_ids(), sc["dwell"]["visit_ms"]
    )
    if not cov.unvisited:
        return FALLBACK_ALL_VISITED
    order = {z: i for i, z in enumerate(config.review_area_ids())}
    dwell = cov.dwell_by_zone
    pick = sorted(cov.unvisited, key=lambda z: (float(dwell.get(z, 0.0)), order.get(z, len(order))))
    pick = sorted(pick[:FALLBACK_MAX_AREAS], key=lambda z: order.get(z, len(order)))
    names = ["the " + FALLBACK_NAMES.get(z, config.zone_human(z)) for z in pick]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
    return f"You haven't looked at {listed} yet."


def hint(
    level: int,
    case: Case,
    marks: list[Mark],
    telemetry: list[TelemetryEvent],
    zones: dict[str, np.ndarray],
    *,
    previous: list | None = None,
) -> str:
    """`previous` = this attempt's hint log ([{level, at, text}]) so the tutor's H3 stays in the zone H2 named."""
    m = _mod("hints")
    if m is not None and hasattr(m, "hint"):
        try:
            return str(m.hint(level, case, marks, telemetry, zones, previous=previous or []))
        except TypeError:  # older tutor signature without `previous`
            try:
                return str(m.hint(level, case, marks, telemetry, zones))
            except Exception:  # noqa: BLE001
                log.exception("tutor.hints.hint failed")
        except Exception:  # noqa: BLE001
            log.exception("tutor.hints.hint failed")
    return fallback_hint(level, case, marks, telemetry, zones)


# ------------------------------------------------------------------ ask
OFFLINE_ANSWER = "The tutor is offline."


def ask(question: str, facts: DebriefFacts | None, case: Case, *, previous: list[dict], offline: bool) -> dict:
    m = _mod("ask")
    if facts is None or m is None or not hasattr(m, "ask"):
        return {"answer": OFFLINE_ANSWER, "source": "template"}
    try:
        out = m.ask(question, facts, case, previous=previous, offline=offline, client=_client)
        return {
            "answer": str(out.get("answer", OFFLINE_ANSWER)),
            "source": out.get("source", "template"),
            "error": out.get("error"),
            "input_tokens": out.get("input_tokens"),
            "output_tokens": out.get("output_tokens"),
            "cache_read_tokens": out.get("cache_read_tokens"),
        }
    except Exception:  # noqa: BLE001
        log.exception("tutor.ask.ask failed")
        return {"answer": OFFLINE_ANSWER, "source": "template", "error": "internal_error"}
