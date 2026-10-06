"""Cost estimator math, cache keys, cache store, bootstrap CI helper."""

from __future__ import annotations

import math

import numpy as np
import pytest

from eval.common import (
    CI,
    BudgetExceeded,
    CallPlan,
    ResponseCache,
    SpendTracker,
    bootstrap_ci,
    bootstrap_paired_diff,
    cache_key,
    check_budget,
    estimate_cost,
    fmt_pct,
    image_tokens,
    parse_price_overrides,
    price_for,
    stable_seed,
    text_tokens,
    usage_cost,
    wilson_ci,
)
from eval.llm import estimate_request_input_tokens, png_dims, request_key, strip_images

PRICES = {"m-small": (2.0, 10.0), "m-big": (4.0, 20.0)}


# ------------------------------------------------------------------------------------------------ cost
def test_estimate_cost_math() -> None:
    est = estimate_cost(
        [CallPlan("a", "m-small", 100, 2000, 500, 1000), CallPlan("b", "m-big", 10, 1000, 100, 400)], PRICES
    )
    # a: 100 × (2000×2 + 500×10)/1e6 = 0.9 ; worst 100 × (4000 + 10000)/1e6 = 1.4
    # b: 10 × (1000×4 + 100×20)/1e6 = 0.06 ; worst 10 × (4000 + 8000)/1e6 = 0.12
    assert est.expected_usd == pytest.approx(0.96)
    assert est.worst_usd == pytest.approx(1.52)
    assert "**0.96**" in est.table()


def test_zero_calls_cost_nothing_even_for_unknown_model() -> None:
    assert estimate_cost([CallPlan("x", "unknown-model", 0, 10, 10, 10)], PRICES).expected_usd == 0.0


def test_unknown_model_price_refuses() -> None:
    with pytest.raises(SystemExit):
        price_for("not-a-model", PRICES)


def test_price_override_parsing() -> None:
    p = parse_price_overrides(["claude-sonnet-5-5=1.5,7.5", "new-model=3,9"])
    assert p["claude-sonnet-5-5"] == (1.5, 7.5)
    assert p["new-model"] == (3.0, 9.0)
    assert p["claude-opus-5-5"] == (4.0, 20.0)  # default table retained


def test_check_budget_refuses_live_but_not_dry() -> None:
    est = estimate_cost([CallPlan("a", "m-small", 1000, 2000, 500, 1000)], PRICES)  # $9.00
    with pytest.raises(SystemExit):
        check_budget(est, 5.0, dry_run=False)
    check_budget(est, 5.0, dry_run=True)  # prints, never raises
    check_budget(est, 10.0, dry_run=False)


def test_usage_cost_and_tracker_hard_stop() -> None:
    assert usage_cost("m-small", 1_000_000, 0, PRICES) == pytest.approx(2.0)
    assert usage_cost("m-small", 0, 0, PRICES, cache_read_tokens=1_000_000) == pytest.approx(0.2)
    assert usage_cost("m-small", 0, 0, PRICES, cache_write_tokens=1_000_000) == pytest.approx(2.5)
    t = SpendTracker(0.01, PRICES)
    t.add("m-small", {"input_tokens": 1000, "output_tokens": 500})  # 0.002 + 0.005
    t.check()
    t.add("m-small", {"input_tokens": 1000, "output_tokens": 500})
    with pytest.raises(BudgetExceeded):
        t.check()


def test_token_heuristics() -> None:
    assert image_tokens(1024, 1024) == math.ceil(1024 * 1024 / 750)
    assert image_tokens(3000, 3000) == image_tokens(1568, 1568)  # long edge scaled to 1568
    assert text_tokens("x" * 35) == 10


def test_request_input_tokens_reads_png_dims() -> None:
    import base64

    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((300, 200), np.uint8))
    b64 = base64.standard_b64encode(buf.tobytes()).decode()
    assert png_dims(b64) == (200, 300)
    kw = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}],
            }
        ],
    }
    assert estimate_request_input_tokens(kw, 9999) >= image_tokens(200, 300)
    assert estimate_request_input_tokens(kw, 9999) < 9999


# ------------------------------------------------------------------------------------------------ cache
def test_cache_key_deterministic_and_sensitive() -> None:
    k = cache_key("m", {"text": "hi", "schema": {"a": 1}}, ["h1"])
    assert k == cache_key("m", {"schema": {"a": 1}, "text": "hi"}, ["h1"])  # key order irrelevant
    assert len(k) == 64
    assert k != cache_key("m2", {"text": "hi", "schema": {"a": 1}}, ["h1"])
    assert k != cache_key("m", {"text": "hi!", "schema": {"a": 1}}, ["h1"])
    assert k != cache_key("m", {"text": "hi", "schema": {"a": 1}}, ["h2"])


def test_request_key_uses_image_hash_not_bytes() -> None:
    import base64

    a = base64.standard_b64encode(b"\x89PNG-a").decode()
    b = base64.standard_b64encode(b"\x89PNG-b").decode()

    def kw(data: str) -> dict:
        return {
            "model": "m",
            "max_tokens": 10,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                        {"type": "text", "text": "q"},
                    ],
                }
            ],
        }

    assert request_key(kw(a)) == request_key(kw(a))
    assert request_key(kw(a)) != request_key(kw(b))
    stripped, hashes = strip_images(kw(a))
    assert len(hashes) == 1 and "data" not in stripped["messages"][0]["content"][0]["source"]


def test_cache_roundtrip_and_namespaces(tmp_path) -> None:  # noqa: ANN001
    live, mock = ResponseCache(tmp_path, "x/live"), ResponseCache(tmp_path, "x/mock")
    mock.put("ab" * 32, {"parsed": {"v": 1}, "mock": True})
    assert mock.get("ab" * 32)["parsed"] == {"v": 1}
    assert live.get("ab" * 32) is None  # mock outputs are never visible as live ones
    assert ("ab" * 32) in mock
    live.put("cd" * 32, {"model": "m", "mock": False, "usage": {"output_tokens": 300}})
    live.put("ef" * 32, {"model": "m", "mock": False, "usage": {"output_tokens": 500}})
    assert live.observed_output_tokens("m") == pytest.approx(400)
    assert mock.observed_output_tokens("m") is None


def test_stable_seed_is_process_independent() -> None:
    assert stable_seed(0, "cxd_1") == stable_seed(0, "cxd_1")
    assert stable_seed(0, "cxd_1") != stable_seed(1, "cxd_1")


# ------------------------------------------------------------------------------------------------ bootstrap
def test_bootstrap_ci_basic() -> None:
    vals = [0, 1] * 50
    ci = bootstrap_ci(vals, n_boot=1000, seed=0)
    assert ci.point == pytest.approx(0.5) and ci.n == 100
    assert ci.lo < 0.5 < ci.hi
    assert 0.38 < ci.lo < 0.45 and 0.55 < ci.hi < 0.62  # ≈ ±1.96·sqrt(.25/100)
    assert bootstrap_ci(vals, seed=0) == bootstrap_ci(vals, seed=0)  # seeded


def test_bootstrap_ci_edge_cases() -> None:
    assert bootstrap_ci([]).n == 0 and math.isnan(bootstrap_ci([]).point)
    one = bootstrap_ci([0.7])
    assert (one.point, one.lo, one.hi, one.n) == (0.7, 0.7, 0.7, 1)
    assert bootstrap_ci([1, None, float("nan"), 0]).n == 2
    const = bootstrap_ci([1.0] * 20)
    assert const.lo == const.hi == 1.0
    assert "Wilson" in fmt_pct(const)  # collapsed bootstrap → Wilson interval added
    med = bootstrap_ci([1, 2, 3, 100], stat="median", seed=0)
    assert med.point == 2.5


def test_paired_diff_and_wilson() -> None:
    d = bootstrap_paired_diff([1, 1, 1, 0], [0, 0, 1, 0], seed=0)
    assert d.point == pytest.approx(0.5) and d.n == 4
    assert bootstrap_paired_diff([1, None], [0, 0]).n == 1
    lo, hi = wilson_ci(0, 20)
    assert lo == 0.0 and 0.1 < hi < 0.2
    assert isinstance(fmt_pct(CI(0.5, 0.4, 0.6, 10)), str)
