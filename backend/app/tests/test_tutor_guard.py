"""Graceful degradation when credits run out, the API rate-limits or fails, or spend exceeds the budget.

Error classification (SDK exceptions with fake httpx responses) · guard state machine with a fake clock (credits
cooldown + doubling probe, rate 60 s, auth until resume, 3x unavailable) · persistence across a restart ·
budget windows and pause · health + admin endpoints (spend hidden from the public) · analytics fire-and-forget ·
end-to-end: a session whose debriefs show error=credits_depleted and health tutor.mode=paused_credits, resuming
after the cooldown. Mocks only; never the network.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from backend.app import tutor_bridge
from backend.app.db import now_iso, tx
from backend.app.settings import get_settings
from backend.app.tests._tutor_helpers import facts_for, fixture_root
from backend.app.tests.conftest import make_submit
from backend.app.tutor import analytics, guard, service, spend
from backend.app.tutor import ask as ask_mod
from backend.app.tutor.client import (
    ERROR_CODES,
    LOCAL_LIMITER,
    LiveCallError,
    LLMResponse,
    MockClient,
    RateLimiter,
    classify_exception,
    classify_status_error,
    fallback_error,
)
from backend.app.tutor.templates import template_debrief
from shared.contracts import DebriefFacts

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
T0 = 1_800_000_000.0  # 2027-01-15T08:00:00Z


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("unit tests must never construct a real Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    yield
    tutor_bridge.set_client(None)


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock() -> Clock:
    c = Clock()
    guard.set_guard(guard.TutorGuard(clock=c, credit_retry_s=15 * 60, persist=False))
    return c


def _status_error(cls, status, message="x", body=None):
    return cls(message, response=httpx2.Response(status, request=REQ), body=body)


def valid(name="found"):
    f, _, _ = facts_for(name)
    return template_debrief(f).model_dump()


def run(name="found", client=None, **kw):
    f, c, sub = facts_for(name)
    kw.setdefault("offline", False)
    return service.generate_debrief(
        f, c, attempt_id="a1", submit=sub, client=client, cache_get=None, data_root=fixture_root(), **kw
    )


def sdk_resp(text):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        model="fake-model",
        usage=SimpleNamespace(
            input_tokens=1000, output_tokens=200, cache_read_input_tokens=3000, cache_creation_input_tokens=0
        ),
    )


class FakeSDK:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.script.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r(kw) if callable(r) else r


def answer_from_facts(kw):
    """A valid debrief for whatever case the request carries (the template built from its FACTS)."""
    text = kw["messages"][0]["content"][-1]["text"]
    facts = DebriefFacts.model_validate_json(text.split("FACTS:\n", 1)[1])
    return sdk_resp(template_debrief(facts).model_dump_json())


# ----------------------------------------------------------------------------- 1. error classification
@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (
            _status_error(
                anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API."
            ),
            "credits_depleted",
        ),
        (
            _status_error(
                anthropic.PermissionDeniedError,
                403,
                "x",
                body={"error": {"type": "permission_error", "message": "Billing: purchase credits"}},
            ),
            "credits_depleted",
        ),
        (_status_error(anthropic.APIStatusError, 402, "payment required"), "credits_depleted"),
        (_status_error(anthropic.RateLimitError, 429, "rate limited"), "rate_limited"),
        (_status_error(anthropic.OverloadedError, 529, "overloaded"), "unavailable"),
        (_status_error(anthropic.InternalServerError, 500, "boom"), "unavailable"),
        (_status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "auth"),
        (_status_error(anthropic.BadRequestError, 400, "max_tokens too large"), "api"),
        (anthropic.APITimeoutError(request=REQ), "timeout"),
        (anthropic.APIConnectionError(request=REQ), "unavailable"),
    ],
)
def test_classify_sdk_exceptions(exc, kind):
    assert classify_exception(exc) == kind


def test_classify_status_text_rules():
    assert classify_status_error(400, "credit balance too low") == "credits_depleted"
    assert classify_status_error(403, "Billing issue") == "credits_depleted"
    assert classify_status_error(403, "forbidden") == "api"
    assert classify_status_error(503, "") == "unavailable"


@pytest.mark.parametrize(
    ("exc", "error", "calls"),
    [
        (_status_error(anthropic.BadRequestError, 400, "credit balance is too low"), "credits_depleted", 1),
        (_status_error(anthropic.RateLimitError, 429), "rate_limited", 1),
        (_status_error(anthropic.AuthenticationError, 401), "auth", 1),
        (_status_error(anthropic.OverloadedError, 529), "unavailable", 2),  # one retry on 5xx/529
        (_status_error(anthropic.InternalServerError, 500), "unavailable", 2),
        (anthropic.APITimeoutError(request=REQ), "timeout", 1),
    ],
)
def test_wrapper_never_raises_and_sets_error(exc, error, calls, clock):
    sdk = FakeSDK([exc, exc, sdk_resp("{}")])
    r = run("found", sdk)
    assert r["source"] == "template" and r["error"] == error and r["debrief"] is not None
    assert r["validator"]["fallback_reason"] == f"live_{fallback_kind(error)}"
    assert len(sdk.calls) == calls


def fallback_kind(error: str) -> str:
    return {"unavailable": "unavailable"}.get(error, error)


def test_ask_never_raises_on_credit_error(clock):
    f, c, _ = facts_for("found")
    sdk = FakeSDK([_status_error(anthropic.BadRequestError, 400, "credit balance is too low")])
    r = ask_mod.ask("Where was it?", f, c, offline=False, client=sdk)
    assert r["source"] == "template" and r["error"] == "credits_depleted" and r["answer"]
    assert guard.get_guard().mode == "paused_credits"


def test_error_codes_are_the_documented_set():
    assert set(fallback_error(r) for r in ("offline", "live_credits_depleted", "paused_budget_exceeded")) <= set(
        ERROR_CODES
    )
    assert fallback_error("live_unavailable") == "unavailable" and fallback_error("paused_auth") == "auth"
    assert fallback_error("nonsense") == "internal_error"


# ----------------------------------------------------------------------------- 2. guard state machine
def test_credits_pause_skips_network_and_probes_after_cooldown(clock):
    mc = MockClient([LiveCallError("credits_depleted", "BadRequestError 400"), valid(), valid()])
    r = run(client=mc)
    assert r["error"] == "credits_depleted" and r["validator"]["fallback_reason"] == "live_credits_depleted"
    g = guard.get_guard()
    assert g.mode == "paused_credits" and g.status()["resume_at"] == "2027-01-15T08:15:00Z"
    # paused: the next call never reaches the client
    r = run(client=mc)
    assert r["error"] == "credits_depleted" and r["validator"]["fallback_reason"] == "paused_credits_depleted"
    assert r["validator"]["attempts"][0]["errors"] == ["live call skipped: credits_depleted"]
    assert len(mc.calls) == 1 and mc.responses[0] == valid()  # nothing consumed
    clock.advance(14 * 60)
    assert run(client=mc)["error"] == "credits_depleted" and len(mc.calls) == 1
    clock.advance(61)  # cooldown over: one probe goes through and succeeds
    r = run(client=mc)
    assert r["source"] == "live" and r["error"] is None and len(mc.calls) == 2
    assert g.mode == "live" and g.status() == {"mode": "live", "reason": None, "resume_at": None}


def test_failed_probe_doubles_the_cooldown_up_to_two_hours(clock):
    g = guard.get_guard()
    g.record_failure("credits_depleted")
    assert g.resume_at == T0 + 15 * 60
    expected = [30, 60, 120, 120, 120]  # minutes
    for minutes in expected:
        clock.t = g.resume_at + 1
        assert g.check() is None and g.probing  # the probe is allowed
        assert g.check() is not None  # a second caller during the probe window is still paused
        g.record_failure("credits_depleted")
        assert g.mode == "paused_credits" and g.resume_at == pytest.approx(clock.t + minutes * 60)
    g.record_success()
    assert g.mode == "live" and g.credit_cooldown_s == 15 * 60  # reset after a success


def test_rate_limit_pauses_sixty_seconds_but_local_limiter_does_not(clock):
    g = guard.get_guard()
    g.record_failure("rate_limited", LOCAL_LIMITER)
    assert g.mode == "live"
    g.record_failure("rate_limited", "RateLimitError 429")
    assert g.mode == "paused_rate" and g.check().kind == "rate_limited" and g.check().paused
    clock.advance(59)
    assert g.status()["mode"] == "paused_rate"
    clock.advance(2)
    assert g.status()["mode"] == "live" and g.check() is None and g.mode == "live"


def test_auth_pauses_until_resume(clock):
    g = guard.get_guard()
    g.record_failure("auth")
    assert g.mode == "paused_error" and g.resume_at is None and g.check().kind == "auth"
    clock.advance(10 * 24 * 3600)
    assert g.check() is not None and g.status()["mode"] == "paused_error"
    g.resume()
    assert g.mode == "live" and g.check() is None


def test_three_consecutive_unavailable_pause_five_minutes(clock):
    g = guard.get_guard()
    g.record_failure("unavailable")
    g.record_failure("unavailable")
    g.record_success()  # a success resets the streak
    g.record_failure("unavailable")
    g.record_failure("unavailable")
    assert g.mode == "live"
    g.record_failure("unavailable")
    assert g.mode == "paused_error" and g.check().kind == "unavailable"
    assert g.status()["resume_at"] == "2027-01-15T08:05:00Z"
    clock.advance(301)
    assert g.check() is None and g.mode == "live"


def test_timeouts_and_refusals_never_pause(clock):
    g = guard.get_guard()
    for kind in ("timeout", "refusal", "max_tokens", "empty", "api"):
        for _ in range(4):
            g.record_failure(kind)
    assert g.mode == "live"


def test_rate_pause_turns_debrief_and_ask_into_templates_without_calls(clock):
    mc = MockClient([LiveCallError("rate_limited", "RateLimitError 429"), valid()])
    assert run(client=mc)["error"] == "rate_limited"
    f, c, _ = facts_for("found")
    r = ask_mod.ask("Where was it?", f, c, offline=False, client=mc)
    assert r["source"] == "template" and r["error"] == "rate_limited"
    assert len(mc.calls) == 1


# ----------------------------------------------------------------------------- 3. persistence across a restart
def test_credit_pause_is_restored_from_the_database(api_env, clock):
    api_env()  # fresh temp DB
    g = guard.TutorGuard(clock=clock, credit_retry_s=15 * 60, persist=True)
    g.record_failure("credits_depleted")
    g.record_failure("credits_depleted")  # not probing: cooldown unchanged
    with tx() as con:
        row = con.execute("SELECT value FROM tutor_state WHERE key='guard'").fetchone()
    st = json.loads(row[0])
    assert st["mode"] == "paused_credits" and st["resume_at"] == "2027-01-15T08:15:00Z"
    # "restart": a new process loads the pause instead of hammering the account
    clock.advance(5 * 60)
    g2 = guard.TutorGuard(clock=clock, credit_retry_s=15 * 60, persist=True)
    assert g2.load() and g2.mode == "paused_credits" and g2.resume_at == T0 + 15 * 60
    assert g2.check() is not None
    # after the cooldown nothing is restored
    clock.advance(11 * 60)
    g3 = guard.TutorGuard(clock=clock, credit_retry_s=15 * 60, persist=True)
    assert not g3.load() and g3.mode == "live"


def test_auth_pause_is_not_restored(api_env, clock):
    api_env()
    g = guard.TutorGuard(clock=clock, persist=True)
    g.record_failure("auth")
    g2 = guard.TutorGuard(clock=clock, persist=True)
    assert not g2.load() and g2.mode == "live"


# ----------------------------------------------------------------------------- 4. budget
def test_price_math():
    p = spend.Prices(2.0, 10.0)
    assert p.cost(1_000_000, 0) == 2.0 and p.cost(0, 1_000_000) == 10.0
    assert p.cost(1_000_000, 0, cache_read_tokens=1_000_000) == pytest.approx(0.2)
    assert p.cost(4000, 200, 3000) == pytest.approx((1000 * 2.0 + 3000 * 0.2 + 200 * 10.0) / 1e6)
    resp = LLMResponse(text="", input_tokens=1000, output_tokens=200, cache_read_input_tokens=3000)
    assert spend.call_cost(resp, p) == pytest.approx(p.cost(4000, 200, 3000))


def test_windows_and_boundaries():
    starts = spend.window_starts(T0)
    assert starts == {"hour": "2027-01-15T07:00:00.000Z", "day": "2027-01-15T00:00:00.000Z", "total": None}
    assert spend.next_boundary("hour", T0 + 90) == "2027-01-15T09:00:00.000Z"
    assert spend.next_boundary("day", T0) == "2027-01-16T00:00:00.000Z"
    assert spend.next_boundary("total", T0) is None
    assert spend.exceeded({"hour": 2.0, "day": 0, "total": 0}, spend.Budgets(2.0, 8.0, 60.0)) == "hour"
    assert spend.exceeded({"hour": 5.0, "day": 9, "total": 70}, spend.Budgets(2.0, 8.0, 60.0)) == "total"
    assert spend.exceeded({"hour": 99.0, "day": 99, "total": 99}, spend.Budgets(0, 0, 0)) is None


def _insert_debrief(con, created_at: str, input_tokens: int, output_tokens: int, cache_read: int = 0, source="live"):
    con.execute(
        "INSERT INTO debriefs(id, attempt_id, created_at, status, source, input_tokens, output_tokens, "
        "cache_read_tokens, output_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            f"d{created_at}{input_tokens}",
            "a",
            created_at,
            "ready",
            source,
            input_tokens,
            output_tokens,
            cache_read,
            "{}",
        ),
    )


def test_query_spend_over_debriefs_and_asks(api_env):
    api_env()
    p = spend.Prices(2.0, 10.0)
    with tx() as con:
        _insert_debrief(con, "2027-01-15T07:30:00.000Z", 1_000_000, 0)  # this hour: $2
        _insert_debrief(con, "2027-01-15T02:00:00.000Z", 0, 100_000)  # today: $1
        _insert_debrief(con, "2027-01-14T23:00:00.000Z", 1_000_000, 0, cache_read=1_000_000)  # yesterday: $0.2
        _insert_debrief(con, "2027-01-15T07:40:00.000Z", 5, 5, source="template")  # tokens on a template row count
        con.execute(
            "INSERT INTO asks(id, attempt_id, question, answer, created_at, source, input_tokens, output_tokens) "
            "VALUES ('q1','a','q','a','2027-01-15T07:50:00.000Z','live',500000,0)"
        )  # this hour: $1
        con.execute(
            "INSERT INTO asks(id, attempt_id, question, answer, created_at) VALUES ('q2','a','q','a','2027-01-15T07:55:00.000Z')"
        )
        s = spend.query_spend(con, T0, p)
        rep = spend.report(con, T0, p)
    assert s["hour"] == pytest.approx(3.00006, abs=1e-5)
    assert s["day"] == pytest.approx(4.00006, abs=1e-5)
    assert s["total"] == pytest.approx(4.20006, abs=1e-5)
    assert rep["debriefs"] == {"live": 3, "cache": 0, "template": 1} and rep["asks"] == {"total": 2, "live": 1}
    assert [b["bucket"] for b in rep["by_hour"]] == ["2027-01-14T23", "2027-01-15T02", "2027-01-15T07"]
    assert rep["by_day"][0]["bucket"] == "2027-01-14" and rep["by_day"][-1]["n"] == 4


def test_budget_pause_and_release(api_env, clock, monkeypatch):
    api_env()
    monkeypatch.setenv("BLINDSPOT_BUDGET_USD_HOURLY", "1.0")
    monkeypatch.setenv("BLINDSPOT_BUDGET_USD_DAILY", "0")
    monkeypatch.setenv("BLINDSPOT_BUDGET_USD_TOTAL", "0")
    get_settings.cache_clear()
    with tx() as con:
        _insert_debrief(con, "2027-01-15T07:30:00.000Z", 600_000, 0)  # $1.2 this hour
    mc = MockClient([valid(), valid()])
    r = run(client=mc)
    g = guard.get_guard()
    assert r["error"] == "budget_exceeded" and mc.calls == [] and g.mode == "paused_budget"
    assert "hourly budget of $1.00" in g.reason and g.status()["resume_at"] == "2027-01-15T09:00:00Z"
    assert r["validator"]["fallback_reason"] == "paused_budget_exceeded"
    # the hour rolls over (cache expired): the spend window no longer includes the row -> live again
    clock.advance(3600 + 1)
    r = run(client=mc)
    assert r["source"] == "live" and g.mode == "live" and len(mc.calls) == 1
    # a live call adds its own cost to the cached snapshot immediately
    assert spend.cache().values["hour"] == pytest.approx(r["cost_usd"]) and r["cost_usd"] > 0


def test_total_budget_has_no_resume_time(api_env, clock, monkeypatch):
    api_env()
    monkeypatch.setenv("BLINDSPOT_BUDGET_USD_TOTAL", "0.5")
    get_settings.cache_clear()
    with tx() as con:
        _insert_debrief(con, "2020-01-01T00:00:00.000Z", 300_000, 0)  # $0.6 ever
    r = run(client=MockClient([valid()]))
    assert r["error"] == "budget_exceeded"
    assert guard.get_guard().status() == {
        "mode": "paused_budget",
        "reason": "total budget of $0.50 reached (BLINDSPOT_BUDGET_USD_TOTAL)",
        "resume_at": None,
    }


# ----------------------------------------------------------------------------- 5. health + admin endpoints
def _live_env(api_env, monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    c = api_env()
    monkeypatch.setenv("BLINDSPOT_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    return c


def test_health_hides_spend_from_the_public(api_env, monkeypatch, clock):
    c = _live_env(api_env, monkeypatch, BLINDSPOT_REVIEW_CODE="radio")
    t = c.get("/api/health").json()["tutor"]
    assert t == {"mode": "live", "reason": None, "resume_at": None, "spend_usd": None, "budget_usd": None}
    t = c.get("/api/health", headers={"X-Blindspot-Review": "radio"}).json()["tutor"]
    assert t["spend_usd"] == {"hour": 0.0, "day": 0.0, "total": 0.0}
    assert t["budget_usd"] == {"hour": 2.0, "day": 8.0, "total": 60.0}
    c.post("/api/review/access", json={"code": "radio"})  # cookie works too
    assert c.get("/api/health").json()["tutor"]["spend_usd"] is not None


def test_health_reports_offline_without_a_key(api_env):
    c = api_env()
    t = c.get("/api/health").json()["tutor"]
    assert t["mode"] == "offline" and t["resume_at"] is None


def test_admin_spend_and_resume_are_review_gated(api_env, monkeypatch, clock):
    c = _live_env(api_env, monkeypatch, BLINDSPOT_REVIEW_CODE="radio")
    assert c.get("/api/admin/spend").status_code == 401
    assert c.post("/api/admin/tutor/resume").status_code == 401
    h = {"X-Blindspot-Review": "radio"}
    guard.get_guard().record_failure("credits_depleted")
    rep = c.get("/api/admin/spend", headers=h).json()
    assert set(rep) >= {"spend_usd", "by_hour", "by_day", "debriefs", "asks", "budget_usd", "tutor", "guard"}
    assert rep["tutor"]["mode"] == "paused_credits" and rep["guard"]["credit_cooldown_s"] == 900
    assert rep["debriefs"] == {"live": 0, "cache": 0, "template": 0}
    r = c.post("/api/admin/tutor/resume", headers=h).json()
    assert r["ok"] and r["tutor"]["mode"] == "live" and r["tutor"]["spend_usd"] is not None
    assert c.get("/api/health").json()["tutor"]["mode"] == "live"


# ----------------------------------------------------------------------------- 6. analytics
def test_analytics_is_disabled_without_a_url(monkeypatch):
    calls = []
    monkeypatch.setattr(analytics, "post_json", lambda *a, **k: calls.append(a))
    assert analytics.track("debrief_live") is False and calls == []


def test_analytics_posts_fire_and_forget(monkeypatch):
    monkeypatch.setenv("BLINDSPOT_ANALYTICS_URL", "https://example.invalid/base/")
    get_settings.cache_clear()
    got, done = [], threading.Event()

    def fake_post(url, body, timeout=3.0):
        got.append((url, body, timeout))
        if len(got) == 3:
            done.set()
        if body["event"] == "ask":
            raise OSError("worker down")  # swallowed

    monkeypatch.setattr(analytics, "post_json", fake_post)
    analytics.report_spend(0.0123456789)
    analytics.report_debrief({"source": "template"})
    analytics.report_ask()
    assert done.wait(2.0)
    assert {u for u, _, _ in got} == {"https://example.invalid/base/analytics/track"}
    assert {json.dumps(b, sort_keys=True) for _, b, _ in got} == {
        json.dumps({"site": "blindspot", "event": "tutor_spend_usd", "value": 0.012346}, sort_keys=True),
        json.dumps({"site": "blindspot", "event": "debrief_template"}, sort_keys=True),
        json.dumps({"site": "blindspot", "event": "ask"}, sort_keys=True),
    }
    assert all(t == 3.0 for _, _, t in got)
    get_settings.cache_clear()


def test_live_call_reports_spend_and_debrief_live(monkeypatch, clock):
    monkeypatch.setenv("BLINDSPOT_ANALYTICS_URL", "https://example.invalid")
    get_settings.cache_clear()
    events, lock = [], threading.Lock()

    def fake_post(url, body, timeout=3.0):
        with lock:
            events.append(body)

    monkeypatch.setattr(analytics, "post_json", fake_post)
    r = run(client=MockClient([valid()]))  # MockClient: 100 in / 50 out tokens
    assert r["source"] == "live" and r["cost_usd"] == pytest.approx((100 * 2.0 + 50 * 10.0) / 1e6)
    for _ in range(50):
        with lock:
            if len(events) >= 2:
                break
        threading.Event().wait(0.02)
    names = sorted(e["event"] for e in events)
    assert names == ["debrief_live", "tutor_spend_usd"]
    assert next(e for e in events if e["event"] == "tutor_spend_usd")["value"] == pytest.approx(r["cost_usd"])
    get_settings.cache_clear()


# ----------------------------------------------------------------------------- 7. end to end (mock, no network)
def _body(**kw) -> dict:
    return json.loads(make_submit(**kw).model_dump_json())


def _session(c):
    r = c.post("/api/sessions", json={"display_name": "Test", "level": "MS2", "mode": "practice"})
    assert r.status_code == 200, r.text
    return r.json()


def _debrief(c, sid):
    n = c.get(f"/api/sessions/{sid}/next").json()
    assert c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True)).status_code == 200
    return c.get(f"/api/attempts/{n['attempt_id']}/debrief").json(), n["attempt_id"]


def test_session_degrades_on_credit_error_and_resumes_after_cooldown(api_env, monkeypatch, clock):
    c = _live_env(api_env, monkeypatch)
    credit_error = _status_error(anthropic.BadRequestError, 400, "Your credit balance is too low")
    sdk = FakeSDK([credit_error, answer_from_facts, answer_from_facts])
    tutor_bridge.set_client(sdk)
    s = _session(c)
    d1, a1 = _debrief(c, s["session_id"])
    assert d1["status"] == "ready" and d1["source"] == "template" and d1["error"] == "credits_depleted"
    assert d1["debrief"]["headline"]  # the learner still gets the built-in explanation
    t = c.get("/api/health").json()["tutor"]
    assert t["mode"] == "paused_credits" and t["resume_at"] == "2027-01-15T08:15:00Z"
    assert "credit balance" in t["reason"]
    # while paused: debriefs and questions are templates, the API is never called
    d2, _ = _debrief(c, s["session_id"])
    assert d2["error"] == "credits_depleted" and d2["validator"]["fallback_reason"] == "paused_credits_depleted"
    q = c.post(f"/api/attempts/{a1}/ask", json={"question": "Where was it?"}).json()
    assert q["source"] == "template"
    assert len(sdk.calls) == 1
    with tx() as con:
        rows_ = con.execute("SELECT source, error, input_tokens FROM debriefs ORDER BY created_at").fetchall()
    assert [tuple(r) for r in rows_] == [("template", "credits_depleted", None)] * 2
    # the cooldown passes: the next call is the probe, it succeeds, the tutor is live again
    clock.advance(15 * 60 + 1)
    d3, _ = _debrief(c, s["session_id"])
    assert d3["source"] in ("live", "cache") and d3.get("error") is None, d3
    assert c.get("/api/health").json()["tutor"]["mode"] == "live"
    assert len(sdk.calls) == 2
    with tx() as con:
        last = con.execute(
            "SELECT input_tokens, output_tokens, cache_read_tokens FROM debriefs WHERE source='live'"
        ).fetchone()
    assert tuple(last) == (4000, 200, 3000)


def test_rate_limiter_still_raises_local_kind():
    tc = RateLimiter(0)
    assert not tc.try_acquire(0.0)
    assert now_iso().endswith("Z")
