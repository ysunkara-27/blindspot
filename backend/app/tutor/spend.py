"""Estimated Anthropic spend and budget limits (deploy/README.md "Tutor guard and budget").

Spend is estimated from the token counts stored with every live call (debriefs + asks tables) at the prices in env:
BLINDSPOT_PRICE_IN_PER_MTOK (default 2.0), BLINDSPOT_PRICE_OUT_PER_MTOK (default 10.0), USD per million tokens;
cached input tokens at 10% of the input price. Limits: BLINDSPOT_BUDGET_USD_HOURLY (2.0), _DAILY (8.0), _TOTAL (60.0);
0 = unlimited. The three windows (last hour, current UTC day, all time) come from one indexed query per table, cached
for CACHE_S seconds; every live call adds its own cost to the cached snapshot so the guard never lags behind.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.settings import get_settings

log = logging.getLogger("blindspot.tutor.spend")

CACHE_S = 10.0
CACHED_INPUT_FACTOR = 0.10
WINDOWS = ("hour", "day", "total")


@dataclass(frozen=True)
class Prices:
    in_per_mtok: float
    out_per_mtok: float

    @classmethod
    def from_settings(cls) -> Prices:
        s = get_settings()
        return cls(float(s.blindspot_price_in_per_mtok), float(s.blindspot_price_out_per_mtok))

    def cost(self, input_tokens: int | None, output_tokens: int | None, cache_read_tokens: int | None = None) -> float:
        """USD for one call. `input_tokens` is the total prompt size (cache reads included, as the service stores
        it); cache reads are re-priced at CACHED_INPUT_FACTOR."""
        inp = max(0, int(input_tokens or 0))
        cached = min(inp, max(0, int(cache_read_tokens or 0)))
        out = max(0, int(output_tokens or 0))
        usd = ((inp - cached) + cached * CACHED_INPUT_FACTOR) * self.in_per_mtok + out * self.out_per_mtok
        return usd / 1e6


@dataclass(frozen=True)
class Budgets:
    hour: float
    day: float
    total: float

    @classmethod
    def from_settings(cls) -> Budgets:
        s = get_settings()
        return cls(
            max(0.0, float(s.blindspot_budget_usd_hourly)),
            max(0.0, float(s.blindspot_budget_usd_daily)),
            max(0.0, float(s.blindspot_budget_usd_total)),
        )

    def as_dict(self) -> dict[str, float]:
        return {"hour": self.hour, "day": self.day, "total": self.total}


def call_cost(resp: Any, prices: Prices | None = None) -> float:
    """Cost of one LLMResponse-like object (input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens)."""
    p = prices or Prices.from_settings()
    inp = (
        (getattr(resp, "input_tokens", 0) or 0)
        + (getattr(resp, "cache_read_input_tokens", 0) or 0)
        + (getattr(resp, "cache_creation_input_tokens", 0) or 0)
    )
    return p.cost(inp, getattr(resp, "output_tokens", 0), getattr(resp, "cache_read_input_tokens", 0))


# ------------------------------------------------------------------ time windows (UTC)
def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def window_starts(now: float) -> dict[str, str | None]:
    """ISO start of each window (None = all time), comparable with db.now_iso() strings."""
    t = datetime.fromtimestamp(now, UTC)
    return {
        "hour": _iso(t - timedelta(hours=1)),
        "day": _iso(t.replace(hour=0, minute=0, second=0, microsecond=0)),
        "total": None,
    }


def next_boundary(window: str, now: float) -> str | None:
    """When a window's limit stops applying: the next hour / next UTC midnight; None for the total."""
    t = datetime.fromtimestamp(now, UTC)
    if window == "hour":
        return _iso((t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
    if window == "day":
        return _iso((t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
    return None


# ------------------------------------------------------------------ queries
_TOKEN_SUM = (
    "COALESCE(SUM(CASE WHEN {w} THEN COALESCE(input_tokens,0) - MIN(COALESCE(cache_read_tokens,0), "
    "COALESCE(input_tokens,0)) END),0), "
    "COALESCE(SUM(CASE WHEN {w} THEN MIN(COALESCE(cache_read_tokens,0), COALESCE(input_tokens,0)) END),0), "
    "COALESCE(SUM(CASE WHEN {w} THEN COALESCE(output_tokens,0) END),0)"
)


def _usd_windows(con: Any, table: str, starts: dict[str, str | None], prices: Prices) -> dict[str, float]:
    """One query: (uncached input, cached input, output) token sums per window for rows with recorded tokens."""
    parts, args = [], []
    for w in WINDOWS:
        cond = "created_at >= ?" if starts[w] else "1"
        if starts[w]:
            args += [starts[w]] * _TOKEN_SUM.count("{w}")
        parts.append(_TOKEN_SUM.format(w=cond))
    sql = f"SELECT {', '.join(parts)} FROM {table} WHERE input_tokens IS NOT NULL"
    r = con.execute(sql, args).fetchone()
    out = {}
    for i, w in enumerate(WINDOWS):
        plain, cached, outp = r[3 * i], r[3 * i + 1], r[3 * i + 2]
        out[w] = ((plain + cached * CACHED_INPUT_FACTOR) * prices.in_per_mtok + outp * prices.out_per_mtok) / 1e6
    return out


def query_spend(con: Any, now: float | None = None, prices: Prices | None = None) -> dict[str, float]:
    """{"hour", "day", "total"} USD over debriefs + asks."""
    now = time.time() if now is None else now
    p = prices or Prices.from_settings()
    starts = window_starts(now)
    tot = dict.fromkeys(WINDOWS, 0.0)
    for table in ("debriefs", "asks"):
        for w, usd in _usd_windows(con, table, starts, p).items():
            tot[w] += usd
    return {w: round(v, 6) for w, v in tot.items()}


def exceeded(spend: dict[str, float], budgets: Budgets) -> str | None:
    """Name of the first window whose limit (> 0) is reached, else None. Order: total, day, hour."""
    for w, limit in (("total", budgets.total), ("day", budgets.day), ("hour", budgets.hour)):
        if limit > 0 and spend.get(w, 0.0) >= limit:
            return w
    return None


# ------------------------------------------------------------------ cached snapshot
@dataclass
class SpendCache:
    """Process-wide snapshot of the three windows, refreshed from the DB at most every CACHE_S seconds."""

    ttl_s: float = CACHE_S
    values: dict[str, float] = field(default_factory=lambda: dict.fromkeys(WINDOWS, 0.0))
    fetched_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get(self, now: float | None = None, *, force: bool = False) -> dict[str, float]:
        now = time.time() if now is None else now
        with self._lock:
            stale = self.fetched_at is None or now - self.fetched_at >= self.ttl_s or force
            if stale:
                try:
                    from backend.app.db import connect

                    con = connect()
                    try:
                        self.values = query_spend(con, now)
                    finally:
                        con.close()
                    self.fetched_at = now
                except Exception:  # noqa: BLE001 — a spend query must never block a debrief
                    log.exception("spend query failed")
                    if self.fetched_at is None:
                        self.fetched_at = now  # do not retry on every call
            return dict(self.values)

    def add(self, usd: float) -> None:
        """A live call just cost `usd`: keep the snapshot current until the next refresh."""
        with self._lock:
            for w in WINDOWS:
                self.values[w] = self.values.get(w, 0.0) + usd

    def clear(self) -> None:
        with self._lock:
            self.fetched_at = None
            self.values = dict.fromkeys(WINDOWS, 0.0)


_CACHE = SpendCache()


def cache() -> SpendCache:
    return _CACHE


def reset_cache() -> None:
    _CACHE.clear()


# ------------------------------------------------------------------ admin report
def report(con: Any, now: float | None = None, prices: Prices | None = None) -> dict[str, Any]:
    """Spend by hour (last 24 h), by day (30 days), totals and debrief counts by source. USD estimated at the current
    env prices. n = number of rows with recorded tokens."""
    now = time.time() if now is None else now
    p = prices or Prices.from_settings()
    t = datetime.fromtimestamp(now, UTC)
    since_h = _iso((t - timedelta(hours=23)).replace(minute=0, second=0, microsecond=0))
    since_d = _iso((t - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0))

    def bucket(width: int, since: str) -> list[dict[str, Any]]:
        acc: dict[str, dict[str, float]] = {}
        for table in ("debriefs", "asks"):
            sql = (
                f"SELECT substr(created_at,1,{width}) AS b, COUNT(*), "
                "SUM(COALESCE(input_tokens,0) - MIN(COALESCE(cache_read_tokens,0), COALESCE(input_tokens,0))), "
                "SUM(MIN(COALESCE(cache_read_tokens,0), COALESCE(input_tokens,0))), SUM(COALESCE(output_tokens,0)) "
                f"FROM {table} WHERE input_tokens IS NOT NULL AND created_at >= ? GROUP BY b"
            )
            for b, n, plain, cached, outp in con.execute(sql, (since,)).fetchall():
                a = acc.setdefault(b, {"n": 0, "usd": 0.0})
                a["n"] += n
                a["usd"] += ((plain + cached * CACHED_INPUT_FACTOR) * p.in_per_mtok + outp * p.out_per_mtok) / 1e6
        return [{"bucket": b, "n": int(v["n"]), "usd": round(v["usd"], 6)} for b, v in sorted(acc.items())]

    counts = {
        r[0] or "unknown": r[1]
        for r in con.execute("SELECT source, COUNT(*) FROM debriefs WHERE status='ready' GROUP BY source").fetchall()
    }
    asks = con.execute("SELECT COUNT(*), SUM(CASE WHEN source='live' THEN 1 ELSE 0 END) FROM asks").fetchone()
    return {
        "spend_usd": query_spend(con, now, p),
        "by_hour": bucket(13, since_h),
        "by_day": bucket(10, since_d),
        "debriefs": {k: counts.get(k, 0) for k in ("live", "cache", "template")},
        "asks": {"total": int(asks[0] or 0), "live": int(asks[1] or 0)},
        "prices_usd_per_mtok": {
            "input": p.in_per_mtok,
            "output": p.out_per_mtok,
            "cached_input_factor": CACHED_INPUT_FACTOR,
        },
    }
