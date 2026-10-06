"""Process-wide tutor guard: pauses live calls when the account is out of credits, rate limited, rejected, failing,
or over budget, so the app degrades to templates visibly instead of hammering the API (deploy/README.md).

Modes (shared.contracts.TutorStatus): live | paused_credits | paused_rate | paused_error | paused_budget (offline is
decided by settings, see tutor_status()).
  credits_depleted -> paused_credits for BLINDSPOT_CREDIT_RETRY_MIN (default 15 min). After the cooldown ONE call
      goes through as a probe; if it fails on credits again the cooldown doubles, up to 2 h.
  rate_limited (429) -> paused_rate for 60 s (the in-process per-minute limiter does not pause).
  auth (401) -> paused_error with no resume_at: until restart or POST /api/admin/tutor/resume.
  3 consecutive unavailable (5xx / 529 / connection) -> paused_error for 5 min.
  budget (backend/app/tutor/spend.py) -> paused_budget until the hour/day boundary (total: until resumed or raised).
While paused, service.generate_debrief / ask.ask skip the network and return templates whose `error` is the pause
reason. The state is mirrored to the `tutor_state` table so a restarted Space resumes a credit pause.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.app.settings import get_settings
from backend.app.tutor import analytics, spend
from backend.app.tutor.client import LOCAL_LIMITER, LiveCallError, LLMResponse, TutorClient

log = logging.getLogger("blindspot.tutor.guard")

RATE_PAUSE_S = 60.0
ERROR_PAUSE_S = 300.0
UNAVAILABLE_STREAK = 3
CREDIT_MAX_S = 2 * 3600.0
PROBE_WINDOW_S = 30.0  # while the post-cooldown probe is in flight, other callers stay paused
STATE_KEY = "guard"
PAUSED = ("paused_credits", "paused_rate", "paused_error", "paused_budget")


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class TutorGuard:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        credit_retry_s: float | None = None,
        persist: bool = True,
    ) -> None:
        self.clock = clock
        base = credit_retry_s if credit_retry_s is not None else float(get_settings().blindspot_credit_retry_min) * 60
        self.credit_retry_s = max(1.0, base)
        self.credit_cooldown_s = self.credit_retry_s
        self.persist = persist
        self.mode = "live"
        self.reason: str | None = None
        self.resume_at: float | None = None
        self.kind: str | None = None  # LiveCallError.kind handed to callers while paused
        self.unavailable_streak = 0
        self.probing = False
        self.paused_since: float | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------ state changes
    def _set(self, mode: str, reason: str | None, resume_at: float | None, kind: str | None) -> None:
        self.mode, self.reason, self.resume_at, self.kind = mode, reason, resume_at, kind
        self.paused_since = self.clock() if mode in PAUSED else None
        if mode != "paused_credits":
            self.probing = False
        self._save()

    def _set_live(self) -> None:
        if self.mode != "live":
            log.info("tutor guard: %s -> live", self.mode)
        self._set("live", None, None, None)

    def check(self) -> LiveCallError | None:
        """Before a live call: the LiveCallError to hand back (paused), or None when the call may go ahead."""
        with self._lock:
            if self.mode == "live" or self.mode == "paused_budget":  # budget is re-evaluated by before_live_call
                return None
            now = self.clock()
            if self.resume_at is not None and now >= self.resume_at:
                if self.mode == "paused_credits":
                    # cooldown over: let exactly one call through as a probe; others wait for its result
                    self.probing = True
                    self._set(
                        "paused_credits",
                        "probing the API after the credit cooldown",
                        now + PROBE_WINDOW_S,
                        "credits_depleted",
                    )
                    return None
                self._set_live()
                return None
            return LiveCallError(self.kind or "unavailable", self.reason or self.mode, paused=True)

    def record_success(self) -> None:
        with self._lock:
            self.unavailable_streak = 0
            self.credit_cooldown_s = self.credit_retry_s
            if self.mode != "paused_budget":
                self._set_live()

    def record_failure(self, kind: str, detail: str = "") -> None:
        with self._lock:
            now = self.clock()
            if kind == "credits_depleted":
                if self.mode == "paused_credits" and self.probing:
                    self.credit_cooldown_s = min(CREDIT_MAX_S, self.credit_cooldown_s * 2)
                cooldown = self.credit_cooldown_s
                self._set(
                    "paused_credits",
                    f"Anthropic credit balance exhausted; retrying in {int(cooldown // 60)} min",
                    now + cooldown,
                    "credits_depleted",
                )
                log.warning("tutor guard: credits depleted, paused for %.0f s", cooldown)
            elif kind == "rate_limited":
                if detail == LOCAL_LIMITER:
                    return
                self._set(
                    "paused_rate",
                    "API rate limit (429); pausing live calls for 60 s",
                    now + RATE_PAUSE_S,
                    "rate_limited",
                )
            elif kind == "auth":
                self._set(
                    "paused_error",
                    "API key rejected (401); fix ANTHROPIC_API_KEY and restart, or POST /api/admin/tutor/resume",
                    None,
                    "auth",
                )
                log.error("tutor guard: authentication failed; live calls paused until restart")
            elif kind == "unavailable":
                self.unavailable_streak += 1
                if self.unavailable_streak >= UNAVAILABLE_STREAK:
                    self.unavailable_streak = 0
                    self._set(
                        "paused_error",
                        f"{UNAVAILABLE_STREAK} consecutive API failures; pausing live calls for 5 min",
                        now + ERROR_PAUSE_S,
                        "unavailable",
                    )
            # timeouts, refusals, local-limiter hits and other 4xx do not pause

    def pause_budget(self, window: str, limit_usd: float, resume_at_iso: str | None) -> None:
        with self._lock:
            label = {"hour": "hourly", "day": "daily", "total": "total"}.get(window, window)
            reason = f"{label} budget of ${limit_usd:.2f} reached (BLINDSPOT_BUDGET_USD_{label.upper()})"
            if self.mode != "paused_budget" or self.reason != reason:
                log.warning("tutor guard: %s", reason)
                self._set("paused_budget", reason, _parse_iso(resume_at_iso), "budget_exceeded")

    def clear_budget(self) -> None:
        with self._lock:
            if self.mode == "paused_budget":
                self._set_live()

    def resume(self) -> None:
        """Clear any pause early (POST /api/admin/tutor/resume)."""
        with self._lock:
            self.unavailable_streak = 0
            self.credit_cooldown_s = self.credit_retry_s
            self._set_live()

    # ------------------------------------------------------------ views
    def status(self) -> dict[str, Any]:
        """TutorStatus fields (mode, reason, resume_at) as the next caller would experience them."""
        with self._lock:
            mode, reason, resume_at = self.mode, self.reason, self.resume_at
            if mode in ("paused_rate", "paused_error") and resume_at is not None and self.clock() >= resume_at:
                mode, reason, resume_at = "live", None, None
            return {"mode": mode, "reason": reason, "resume_at": _iso(resume_at)}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self.status(),
                "stored_mode": self.mode,
                "kind": self.kind,
                "paused_since": _iso(self.paused_since),
                "credit_cooldown_s": self.credit_cooldown_s,
                "unavailable_streak": self.unavailable_streak,
                "probing": self.probing,
            }

    # ------------------------------------------------------------ persistence (tutor_state table)
    def _save(self) -> None:
        if not self.persist:
            return
        try:
            from backend.app.db import now_iso, tx

            value = json.dumps(
                {
                    "mode": self.mode,
                    "reason": self.reason,
                    "resume_at": _iso(self.resume_at),
                    "kind": self.kind,
                    "credit_cooldown_s": self.credit_cooldown_s,
                    "saved_at": now_iso(),
                }
            )
            with tx() as con:
                con.execute(
                    "INSERT INTO tutor_state(key, value, updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (STATE_KEY, value, now_iso()),
                )
        except Exception:  # noqa: BLE001 — persistence is best-effort
            log.exception("tutor guard: could not save state")

    def load(self) -> bool:
        """Restore a pause saved by an earlier process. Only pauses with a future resume_at come back (a credit or
        rate/error pause); an auth pause clears on restart (the key may have been fixed) and a budget pause is
        recomputed from spend. Returns True when something was restored."""
        try:
            from backend.app.db import connect

            con = connect()
            try:
                r = con.execute("SELECT value FROM tutor_state WHERE key=?", (STATE_KEY,)).fetchone()
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            log.exception("tutor guard: could not load state")
            return False
        if not r:
            return False
        try:
            st = json.loads(r[0])
        except ValueError:
            return False
        resume_at = _parse_iso(st.get("resume_at"))
        mode = st.get("mode")
        with self._lock:
            if mode == "paused_credits":
                self.credit_cooldown_s = min(
                    CREDIT_MAX_S, max(self.credit_retry_s, float(st.get("credit_cooldown_s") or 0))
                )
            if mode in ("paused_credits", "paused_rate", "paused_error") and resume_at and resume_at > self.clock():
                self.mode, self.reason, self.resume_at, self.kind = mode, st.get("reason"), resume_at, st.get("kind")
                self.paused_since = self.clock()
                log.warning("tutor guard: resumed %s from the database (until %s)", mode, _iso(resume_at))
                return True
        return False


# ------------------------------------------------------------------ singleton + call wrapper
_GUARD: TutorGuard | None = None
_GUARD_LOCK = threading.Lock()


def get_guard() -> TutorGuard:
    global _GUARD
    if _GUARD is None:
        with _GUARD_LOCK:
            if _GUARD is None:
                g = TutorGuard()
                g.load()
                _GUARD = g
    return _GUARD


def set_guard(guard: TutorGuard | None) -> None:
    """Tests: install a guard with a fake clock (None = a fresh, non-persisting guard on next use)."""
    global _GUARD
    _GUARD = guard


def before_live_call() -> LiveCallError | None:
    """Pause check + budget check. Returns the LiveCallError (paused=True) that the caller should turn into a
    template, or None when the call may go to the network."""
    g = get_guard()
    err = g.check()
    if err is not None:
        return err
    try:
        now = g.clock()
        budgets = spend.Budgets.from_settings()
        over = spend.exceeded(spend.cache().get(now), budgets)
    except Exception:  # noqa: BLE001 — a budget bookkeeping bug must not stop the tutor
        log.exception("budget check failed")
        over = None
    if over:
        limit = getattr(budgets, over)
        g.pause_budget(over, limit, spend.next_boundary(over, now))
        return LiveCallError("budget_exceeded", g.reason or "budget reached", paused=True)
    g.clear_budget()
    return None


def guarded_complete(
    tc: TutorClient,
    *,
    system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    max_tokens: int,
) -> LLMResponse:
    """tc.complete() behind the guard: raises LiveCallError(paused=True) without touching the network while paused
    or over budget; records the outcome; prices the call (resp.cost_usd) and reports it to analytics."""
    blocked = before_live_call()
    if blocked is not None:
        raise blocked
    g = get_guard()
    try:
        resp = tc.complete(system=system, messages=messages, schema=schema, max_tokens=max_tokens)
    except LiveCallError as e:
        g.record_failure(e.kind, e.detail)
        raise
    g.record_success()
    try:
        usd = spend.call_cost(resp)
        resp.cost_usd = usd
        spend.cache().add(usd)
        analytics.report_spend(usd)
    except Exception:  # noqa: BLE001
        log.exception("spend bookkeeping failed")
    return resp


def tutor_status(*, include_spend: bool) -> dict[str, Any]:
    """Health `tutor` object. Spend and budget only for review-gated callers (include_spend)."""
    s = get_settings()
    if s.offline:
        st: dict[str, Any] = {
            "mode": "offline",
            "reason": "BLINDSPOT_OFFLINE=1" if s.blindspot_offline else "no ANTHROPIC_API_KEY",
            "resume_at": None,
        }
    else:
        st = get_guard().status()
    st["spend_usd"] = st["budget_usd"] = None
    if include_spend:
        try:
            st["spend_usd"] = spend.cache().get(get_guard().clock())
            st["budget_usd"] = spend.Budgets.from_settings().as_dict()
        except Exception:  # noqa: BLE001
            log.exception("spend snapshot failed")
    return st
