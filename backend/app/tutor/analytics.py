"""Fire-and-forget usage events for the site analytics worker (ysunkara.com/stats).

POST {BLINDSPOT_ANALYTICS_URL}/analytics/track with {"site": "blindspot", "event": <name>, "value": <number>?}.
Empty URL (the default, and always in unit tests) = disabled. Each event is sent from a daemon thread with a 3 s
timeout; nothing here ever blocks a request or raises. Events: tutor_spend_usd (value = USD of one live call),
debrief_live, debrief_template, ask.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from typing import Any

from backend.app.settings import get_settings

log = logging.getLogger("blindspot.tutor.analytics")

SITE = "blindspot"
TIMEOUT_S = 3.0
PATH = "/analytics/track"


def analytics_url() -> str:
    """Base URL from env, or "" when reporting is disabled."""
    return (get_settings().blindspot_analytics_url or "").strip().rstrip("/")


def payload(event: str, value: float | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"site": SITE, "event": event}
    if value is not None:
        body["value"] = round(float(value), 6)
    return body


def post_json(url: str, body: dict[str, Any], timeout: float = TIMEOUT_S) -> None:
    """Synchronous POST (tests monkeypatch this)."""
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout):  # noqa: S310 — URL comes from our own env
        pass


def track(event: str, value: float | None = None) -> bool:
    """Queue one event. Returns True when a send was started (URL configured), False when disabled."""
    base = analytics_url()
    if not base:
        return False
    body = payload(event, value)

    def _send() -> None:
        try:
            post_json(base + PATH, body)
        except Exception as e:  # noqa: BLE001 — never raise, never retry
            log.debug("analytics event %s not delivered: %s", event, e)

    threading.Thread(target=_send, name="blindspot-analytics", daemon=True).start()
    return True


def report_debrief(out: dict[str, Any] | None) -> None:
    """Count a finished debrief by its source (cache hits are free and not counted)."""
    if not isinstance(out, dict):
        return
    src = out.get("source")
    if src == "live":
        track("debrief_live")
    elif src == "template":
        track("debrief_template")


def report_ask() -> None:
    track("ask")


def report_spend(usd: float | None) -> None:
    if usd is not None and usd > 0:
        track("tutor_spend_usd", usd)
