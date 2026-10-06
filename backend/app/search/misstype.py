"""SPEC §7.2 Kundel miss types (proxy). Thresholds from scoring.yaml['miss_types']."""

from __future__ import annotations

MISS_COPY = {
    "missed_search": "Never looked there",
    "missed_recognition": "Looked past it",
    "missed_decision": "Looked, judged it normal",
    "mislabeled": "Found it, named it wrong",
    "false_positive": "Called something that isn't there",
    "found": "Found it",
}
PROXY_NOTE = "Based on your cursor, loupe and zoom — a proxy for where you looked."

# Outcome result -> miss-type bucket for analytics.
BUCKET = {
    "missed_search": "search",
    "missed_recognition": "recognition",
    "missed_decision": "decision",
    "mislabeled": "interpretation",
    "false_positive": "overcall",
}


def miss_type(dwell_ms: float, cfg: dict) -> str:
    if dwell_ms < cfg["recognition_ms"]:
        return "missed_search"
    if dwell_ms < cfg["decision_ms"]:
        return "missed_recognition"
    return "missed_decision"
