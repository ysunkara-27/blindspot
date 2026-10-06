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
    facts: DebriefFacts, case: Case, *, attempt_id: str, submit: AttemptSubmit, offline: bool, cache_get: Any
) -> dict[str, Any] | None:
    m = _mod("service")
    if m is None or not hasattr(m, "generate_debrief"):
        return None
    try:
        out = m.generate_debrief(
            facts, case, attempt_id=attempt_id, submit=submit, offline=offline, cache_get=cache_get, client=_client
        )
    except Exception:  # noqa: BLE001
        log.exception("tutor.service.generate_debrief failed")
        return None
    if not isinstance(out, dict) or out.get("debrief") is None:
        return None
    d = out["debrief"]
    out["debrief"] = d if isinstance(d, DebriefOutput) else DebriefOutput.model_validate(d)
    return out


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
def _hardest_unmarked(case: Case, marks: list[Mark], tau: float):
    def hit(f) -> bool:
        x0, y0, x1, y1 = f.geometry.bbox
        return any(x0 - tau <= m.x <= x1 + tau and y0 - tau <= m.y <= y1 + tau for m in marks)

    focal = [f for f in case.findings if f.kind == "focal" and not hit(f)]
    if not focal:
        return None
    return max(focal, key=lambda f: f.difficulty if f.difficulty is not None else -f.area_frac)


def fallback_hint(
    level: int, case: Case, marks: list[Mark], telemetry: list[TelemetryEvent], zones: dict[str, np.ndarray]
) -> str:
    """Deterministic §8.8 ladder when the tutor module is unavailable."""
    sc = config.scoring()
    if level == 1:
        cov = review_coverage(
            dwell_samples(telemetry, sc["dwell"]), zones, config.review_area_ids(), sc["dwell"]["visit_ms"]
        )
        if cov.unvisited:
            return "You haven't looked at: " + ", ".join(config.zone_human(z) for z in cov.unvisited) + "."
        return "Compare each region with the same region on the other side."
    f = _hardest_unmarked(case, marks, sc["hit"]["tolerance_frac"] * case.width)
    if case.is_normal or f is None:
        if level == 2:
            return "Asymmetry is the clue: compare left and right zone by zone."
        return "If every review area is clear, normal is a valid call."
    if level == 2:
        side = f.side if f.side in ("right", "left") else None
        where = config.zone_human(f.primary_zone)
        return f"Look again at the {where}" + (f" (patient's {side})." if side else ".")
    card = load_cards().get(f.label)
    if card and card.key_signs:
        return f"Look for this sign: {card.key_signs[0]}"
    return f"Look for a {config.display(f.label).lower()} in the {config.zone_human(f.primary_zone)}."


def hint(
    level: int, case: Case, marks: list[Mark], telemetry: list[TelemetryEvent], zones: dict[str, np.ndarray]
) -> str:
    m = _mod("hints")
    if m is not None and hasattr(m, "hint"):
        try:
            return str(m.hint(level, case, marks, telemetry, zones))
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
        return {"answer": str(out.get("answer", OFFLINE_ANSWER)), "source": out.get("source", "template")}
    except Exception:  # noqa: BLE001
        log.exception("tutor.ask.ask failed")
        return {"answer": OFFLINE_ANSWER, "source": "template"}
