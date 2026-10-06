"""Debrief service flow with mocked clients only (never the network).

live ok · live invalid → regenerate → ok · invalid twice → template · API errors → template · offline → template ·
cache hit / stale cache / template rows · SDK wrapper: request shape, 5xx retry, timeout, refusal · rate limiter.
"""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from backend.app.settings import Settings
from backend.app.tests._tutor_helpers import facts_for, fixture_root
from backend.app.tutor import client as client_mod
from backend.app.tutor import service
from backend.app.tutor.client import AnthropicTutorClient, LiveCallError, MockClient, RateLimiter, debrief_schema
from backend.app.tutor.templates import template_debrief


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("unit tests must never construct a real Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)


def valid_json(name):
    f, _, _ = facts_for(name)
    return template_debrief(f).model_dump()


def run(name, client, **kw):
    f, c, sub = facts_for(name)
    kw.setdefault("offline", False)
    kw.setdefault("cache_get", None)
    return service.generate_debrief(f, c, attempt_id="a1", submit=sub, client=client, data_root=fixture_root(), **kw)


def test_live_ok_and_request_shape():
    mc = MockClient([valid_json("missed_search")])
    r = run("missed_search", mc)
    assert r["source"] == "live" and r["validator"]["ok"] and r["validator"]["first_try_ok"]
    assert r["model"] == "mock-model" and r["input_tokens"] == 100 and r["output_tokens"] == 50
    assert r["provenance"] == "ai_draft" and len(r["cache_key"]) == 64 and r["prompt_version"].startswith("v1+")
    call = mc.calls[0]
    assert len(call["system"]) == 2
    assert call["system"][0]["text"].startswith("You write the debrief for Blindspot")
    assert call["system"][1]["cache_control"] == {"type": "ephemeral"} and "TEACHING CARDS" in call["system"][1]["text"]
    content = call["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "image", "text"]
    assert content[0]["source"]["media_type"] == "image/png"
    assert "FACTS:\n" in content[3]["text"] and '"case_id":"syn_002"' in content[3]["text"]
    assert call["schema"] == debrief_schema() and call["max_tokens"] == 1200


def test_cached_system_prefix_is_identical_across_cases():
    a, b = MockClient([valid_json("found")]), MockClient([valid_json("multi")])
    run("found", a)
    run("multi", b)
    assert a.calls[0]["system"] == b.calls[0]["system"]
    assert a.calls[0]["schema"] == b.calls[0]["schema"]


def test_invalid_then_valid_regenerates_once():
    bad = valid_json("found")
    bad["findings"][0]["why"] = "This might be pneumonia."
    mc = MockClient([bad, valid_json("found")])
    r = run("found", mc)
    assert r["source"] == "live" and r["validator"]["regenerated"] and not r["validator"]["first_try_ok"]
    fix = mc.calls[1]["messages"]
    assert [m["role"] for m in fix] == ["user", "assistant", "user"]
    assert fix[2]["content"].startswith("Fix these problems: R5")


def test_invalid_twice_falls_back_to_template():
    bad = valid_json("found")
    bad["headline"] = " ".join(["long"] * 30)
    mc = MockClient([bad, bad])
    r = run("found", mc)
    assert r["source"] == "template" and r["validator"]["ok"]
    assert r["validator"]["fallback_reason"] == "validator_failed" and len(r["validator"]["attempts"]) == 2
    assert r["input_tokens"] == 200  # spend is still reported


def test_malformed_json_then_template():
    mc = MockClient(["{not json", "also not json"])
    r = run("missed_decision", mc)
    assert r["source"] == "template" and r["validator"]["attempts"][0]["errors"][0].startswith("R0")


@pytest.mark.parametrize("kind", ["timeout", "api", "refusal", "rate_limited", "max_tokens"])
def test_api_errors_fall_back_without_regeneration(kind):
    mc = MockClient([LiveCallError(kind), valid_json("found")])
    r = run("found", mc)
    assert r["source"] == "template" and r["validator"]["fallback_reason"] == f"live_{kind}"
    assert len(mc.calls) == 1


def test_offline_never_calls_client():
    mc = MockClient([valid_json("found")])
    r = run("found", mc, offline=True)
    assert r["source"] == "template" and r["validator"]["ok"] and mc.calls == []
    assert r["validator"]["fallback_reason"] == "offline"


def test_no_api_key_and_no_client_uses_template(monkeypatch):
    s = Settings(_env_file=None, anthropic_api_key=None, blindspot_offline=False)
    monkeypatch.setattr(service, "get_settings", lambda: s)
    r = run("found", None, offline=None)
    assert r["source"] == "template" and r["validator"]["fallback_reason"] in ("offline", "no_api_key")


def test_cache_hit_skips_client_and_is_revalidated():
    first = run("found", MockClient([valid_json("found")]))
    store = {
        first["cache_key"]: {
            "output_json": json.dumps(first["debrief"].model_dump()),
            "source": "live",
            "model": "mock-model",
        }
    }
    mc = MockClient([])
    r = run("found", mc, cache_get=store.get)
    assert r["source"] == "cache" and mc.calls == [] and r["model"] == "mock-model"
    stale = dict(valid_json("found"), verdict="missed")
    r2 = run("found", MockClient([valid_json("found")]), cache_get=lambda k: {"output_json": stale, "source": "live"})
    assert r2["source"] == "live"
    r3 = run(
        "found",
        MockClient([valid_json("found")]),
        cache_get=lambda k: {"output_json": valid_json("found"), "source": "template"},
    )
    assert r3["source"] == "live"


def test_cache_get_errors_are_tolerated():
    def broken(_):
        raise RuntimeError("db down")

    r = run("found", MockClient([valid_json("found")]), cache_get=broken)
    assert r["source"] == "live"


def test_missing_image_still_produces_a_text_only_live_debrief(tmp_path):
    f, c, sub = facts_for("found")
    mc = MockClient([valid_json("found")])
    r = service.generate_debrief(
        f, c, attempt_id="a", submit=sub, offline=False, cache_get=None, client=mc, data_root=tmp_path
    )
    assert r["source"] == "live"
    assert [b["type"] for b in mc.calls[0]["messages"][0]["content"]] == ["text"]


# ----------------------------------------------------------------------------- SDK wrapper (fake SDK object)
REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def sdk_resp(text, stop="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        model="fake-model",
        usage=SimpleNamespace(
            input_tokens=900, output_tokens=210, cache_read_input_tokens=3100, cache_creation_input_tokens=0
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
        return r


def test_sdk_client_request_parameters_and_usage():
    sdk = FakeSDK([sdk_resp(json.dumps(valid_json("found")))])
    r = run("found", sdk)  # an Anthropic-like object is wrapped automatically
    assert r["source"] == "live" and r["model"] == "fake-model"
    assert r["input_tokens"] == 4000 and r["output_tokens"] == 210
    kw = sdk.calls[0]
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": debrief_schema()}
    assert kw["output_config"]["effort"] == "low"
    assert kw["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert kw["max_tokens"] == 1200 and kw["model"]


def test_sdk_one_retry_on_5xx_then_success():
    err = anthropic.InternalServerError("boom", response=httpx2.Response(500, request=REQ), body=None)
    sdk = FakeSDK([err, sdk_resp(json.dumps(valid_json("found")))])
    assert run("found", sdk)["source"] == "live" and len(sdk.calls) == 2


def test_sdk_overloaded_twice_gives_template():
    o = anthropic.OverloadedError("busy", response=httpx2.Response(529, request=REQ), body=None)
    sdk = FakeSDK([o, o])
    r = run("found", sdk)
    assert r["source"] == "template" and r["validator"]["fallback_reason"] == "live_api" and len(sdk.calls) == 2


def test_sdk_timeout_and_4xx_are_not_retried():
    for exc, reason in (
        (anthropic.APITimeoutError(request=REQ), "live_timeout"),
        (anthropic.BadRequestError("bad", response=httpx2.Response(400, request=REQ), body=None), "live_api"),
    ):
        sdk = FakeSDK([exc, sdk_resp("{}")])
        r = run("found", sdk)
        assert r["validator"]["fallback_reason"] == reason and len(sdk.calls) == 1


def test_sdk_refusal_gives_template():
    sdk = FakeSDK([sdk_resp("", stop="refusal")])
    assert run("found", sdk)["validator"]["fallback_reason"] == "live_refusal"


def test_effort_can_be_disabled_for_models_without_it():
    sdk = FakeSDK([sdk_resp(json.dumps(valid_json("found")))])
    tc = AnthropicTutorClient(model="some-model", effort="none", sdk_client=sdk, limiter=RateLimiter(5))
    tc.complete(system=[], messages=[], schema={}, max_tokens=10)
    assert "effort" not in sdk.calls[0]["output_config"]


def test_rate_limiter_window():
    lim = RateLimiter(2)
    assert lim.try_acquire(0.0) and lim.try_acquire(1.0) and not lim.try_acquire(2.0)
    assert lim.try_acquire(61.0)
    tc = AnthropicTutorClient(model="m", sdk_client=FakeSDK([]), limiter=RateLimiter(0))
    with pytest.raises(LiveCallError) as e:
        tc.complete(system=[], messages=[], schema={}, max_tokens=10)
    assert e.value.kind == "rate_limited"


def test_schema_sent_is_the_shared_contract():
    shared = json.loads((client_mod.vocab.SCHEMAS_DIR / "debrief_output.json").read_text())
    s = debrief_schema()
    assert s["properties"] == shared["properties"] and s["required"] == shared["required"]
    assert "$schema" not in s and s["additionalProperties"] is False
