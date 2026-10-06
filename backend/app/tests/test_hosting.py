"""Hosting: access/review code gates (set and unset), base path, SPA serving, cache headers, CORS, plus the
contract additions of this round (review geometry, anatomy outlines, cohort learning curve, summary counts).
Synthetic fixtures only; offline; no Anthropic calls."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.analytics.cohort import cohort_learning_curve
from backend.app.anatomy_outline import MAX_POINTS, mask_outlines
from backend.app.routes.access import reset_failures
from backend.app.settings import get_settings
from backend.app.tests.conftest import make_submit, mark, resplit

ALL_VARS = (
    "BLINDSPOT_ACCESS_CODE",
    "BLINDSPOT_REVIEW_CODE",
    "BLINDSPOT_BASE_PATH",
    "BLINDSPOT_SERVE_FRONTEND",
    "BLINDSPOT_FRONTEND_DIST",
    "BLINDSPOT_CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for v in ALL_VARS:  # "" overrides a value in .env for the string settings; bool/path fall back to defaults
        if v in ("BLINDSPOT_SERVE_FRONTEND", "BLINDSPOT_FRONTEND_DIST"):
            monkeypatch.delenv(v, raising=False)
        else:
            monkeypatch.setenv(v, "")
    reset_failures()
    yield
    reset_failures()
    get_settings.cache_clear()


def _gated(api_env, monkeypatch, **env) -> TestClient:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return api_env()


def _body(**kw) -> dict:
    return json.loads(make_submit(**kw).model_dump_json())


def _practice(c: TestClient, headers=None) -> tuple[dict, dict]:
    s = c.post("/api/sessions", json={"display_name": "H", "level": "MS3", "mode": "practice"}, headers=headers)
    assert s.status_code == 200, s.text
    n = c.get(f"/api/sessions/{s.json()['session_id']}/next", headers=headers)
    assert n.status_code == 200, n.text
    return s.json(), n.json()


# ------------------------------------------------------------------ gates
def test_nothing_gated_when_codes_unset(api_env):
    c = api_env()
    assert c.get("/api/access").json() == {
        "access_required": False,
        "access_granted": True,
        "review_required": False,
        "review_granted": True,
        "base_path": "",
    }
    _practice(c)
    assert c.get("/api/review/items").status_code == 200
    assert c.get("/api/cohort/dashboard").status_code == 200
    assert c.post("/api/access", json={"code": "x"}).json() == {"ok": True, "required": False}


def test_access_code_gates_every_api_route_except_health_about_access(api_env, monkeypatch):
    c = _gated(api_env, monkeypatch, BLINDSPOT_ACCESS_CODE="sesame")
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/about").status_code == 200
    assert c.get("/api/access").json()["access_required"] is True
    for method, path in (
        ("post", "/api/sessions"),
        ("get", "/api/sessions/x/next"),
        ("get", "/api/cases/syn_001/image"),
        ("get", "/api/review/items"),
        ("get", "/api/cohort/dashboard"),
        ("get", "/api/learners/x/dashboard"),
        ("get", "/api/openapi.json"),
    ):
        r = getattr(c, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 401, (path, r.status_code)
        assert r.json() == {"error": "access_code_required"}
    # header works
    _practice(c, headers={"X-Blindspot-Access": "sesame"})
    assert c.post("/api/sessions", json={}, headers={"X-Blindspot-Access": "nope"}).status_code == 401


def test_access_cookie_flow(api_env, monkeypatch):
    c = _gated(api_env, monkeypatch, BLINDSPOT_ACCESS_CODE="sesame")
    bad = c.post("/api/access", json={"code": "wrong"})
    assert bad.status_code == 401 and bad.json() == {"error": "invalid_code"}
    ok = c.post("/api/access", json={"code": "sesame"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    sc = ok.headers["set-cookie"]
    assert "bs_access=" in sc and "HttpOnly" in sc and "SameSite=lax" in sc.replace("Lax", "lax") and "Path=/" in sc
    assert "sesame" not in sc  # the cookie carries a derived token, never the code
    assert "Domain" not in sc
    _, n = _practice(c)  # TestClient keeps the cookie
    img = c.get(n["case"]["image_url"])
    assert img.status_code == 200 and "max-age=31536000" in img.headers["cache-control"]
    assert c.get("/api/access").json()["access_granted"] is True
    c.cookies.set("bs_access", "forged")
    assert c.post("/api/sessions", json={}).status_code == 401


def test_access_failures_are_rate_limited(api_env, monkeypatch):
    c = _gated(api_env, monkeypatch, BLINDSPOT_ACCESS_CODE="sesame")
    codes = [c.post("/api/access", json={"code": f"g{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert c.post("/api/access", json={"code": "sesame"}).status_code == 429


def test_review_code_gates_review_and_cohort(api_env, monkeypatch):
    c = _gated(api_env, monkeypatch, BLINDSPOT_ACCESS_CODE="sesame", BLINDSPOT_REVIEW_CODE="radio")
    assert c.post("/api/review/access", json={"code": "radio"}).status_code == 401  # access gate first
    c.post("/api/access", json={"code": "sesame"})
    _practice(c)  # learner routes need only the access code
    for path in ("/api/review/items", "/api/review/export.csv", "/api/cohort/dashboard"):
        r = c.get(path)
        assert r.status_code == 401 and r.json() == {"error": "review_code_required"}, path
    assert c.get("/api/review/items", headers={"X-Blindspot-Review": "radio"}).status_code == 200
    assert c.post("/api/review/access", json={"code": "nope"}).status_code == 401
    r = c.post("/api/review/access", json={"code": "radio"})
    assert r.status_code == 200 and "bs_review=" in r.headers["set-cookie"]
    assert c.get("/api/cohort/dashboard").status_code == 200
    assert c.get("/api/access").json()["review_granted"] is True


def test_review_only_code_leaves_learner_routes_open(api_env, monkeypatch):
    c = _gated(api_env, monkeypatch, BLINDSPOT_REVIEW_CODE="radio")
    _practice(c)
    assert c.get("/api/cohort/dashboard").status_code == 401


def test_api_responses_are_no_store_images_keep_long_cache(api_env):
    c = api_env()
    _, n = _practice(c)
    assert c.get("/api/health").headers["cache-control"] == "no-store"
    assert c.get("/api/about").headers["cache-control"] == "no-store"
    assert "immutable" in c.get(n["case"]["image_url"]).headers["cache-control"]


# ------------------------------------------------------------------ base path + SPA + CORS
def test_base_path_routes_and_urls(api_env, monkeypatch):
    c = _gated(api_env, monkeypatch, BLINDSPOT_BASE_PATH="/blindspot/", BLINDSPOT_ACCESS_CODE="sesame")
    assert c.get("/blindspot/api/health").status_code == 200
    assert c.get("/api/health").status_code == 200  # a proxy that strips the prefix still works
    assert c.post("/blindspot/api/sessions", json={}).status_code == 401
    r = c.post("/blindspot/api/access", json={"code": "sesame"})
    sc = r.headers["set-cookie"]
    assert "Path=/blindspot" in sc and "Secure" in sc and "HttpOnly" in sc
    hdr = {"X-Blindspot-Access": "sesame"}
    s = c.post("/blindspot/api/sessions", json={"display_name": "B", "level": "MS3", "mode": "practice"}, headers=hdr)
    n = c.get(f"/blindspot/api/sessions/{s.json()['session_id']}/next", headers=hdr).json()
    assert n["case"]["image_url"].startswith("/blindspot/api/cases/")
    assert c.get(n["case"]["image_url"], headers=hdr).status_code == 200
    red = c.get("/blindspot", follow_redirects=False)
    assert red.status_code == 307 and red.headers["location"] == "/blindspot/"
    assert c.get("/blindspot/api/docs", headers=hdr).status_code == 200


def _dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>Blindspot</title>")
    (d / "assets" / "app.js").write_text("console.log(1)")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("no")
    return d


def _fresh_app(api_env, monkeypatch, **env) -> TestClient:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    api_env()  # sets data/db env + clears caches
    from backend.app.main import create_app

    return TestClient(create_app())


def test_serves_spa_under_base_path_with_fallback(api_env, monkeypatch, tmp_path):
    d = _dist(tmp_path)
    c = _fresh_app(
        api_env,
        monkeypatch,
        BLINDSPOT_BASE_PATH="/blindspot",
        BLINDSPOT_SERVE_FRONTEND="1",
        BLINDSPOT_FRONTEND_DIST=str(d),
        BLINDSPOT_ACCESS_CODE="sesame",
    )
    for p in ("/blindspot/", "/blindspot/read", "/blindspot/review/x/y", "/blindspot/progress?x=1"):
        r = c.get(p)
        assert r.status_code == 200 and "<title>Blindspot</title>" in r.text, p  # SPA is not gated (no data)
        assert r.headers["cache-control"] == "no-cache"
    js = c.get("/blindspot/assets/app.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    assert c.get("/blindspot/favicon.svg").text == "<svg/>"
    assert "secret" not in c.get("/blindspot/%2e%2e/secret.txt").text
    assert c.get("/blindspot/api/nope", headers={"X-Blindspot-Access": "sesame"}).status_code == 404
    assert c.get("/blindspot/api/health").json()["ok"] is True


def test_spa_not_served_by_default(api_env):
    c = api_env()
    assert c.get("/").status_code == 404
    assert c.get("/read").status_code == 404


def test_cors_origins_from_env(api_env, monkeypatch):
    c = _fresh_app(api_env, monkeypatch, BLINDSPOT_CORS_ORIGINS="https://ysunkara.com, https://x.example")
    pre = {"Access-Control-Request-Method": "GET"}
    for origin in ("https://ysunkara.com", "http://localhost:5173"):
        r = c.options("/api/health", headers={"Origin": origin, **pre})
        assert r.headers.get("access-control-allow-origin") == origin
    r = c.options("/api/health", headers={"Origin": "https://evil.example", **pre})
    assert r.headers.get("access-control-allow-origin") is None


# ------------------------------------------------------------------ anatomy outlines
def test_mask_outlines_are_simplified():
    yy, xx = np.mgrid[0:256, 0:256]
    m = (xx - 128) ** 2 / 90**2 + (yy - 128) ** 2 / 60**2 < 1  # smooth ellipse → many raw contour points
    m[5:7, 5:7] = True  # speck, dropped
    polys = mask_outlines(m)
    assert len(polys) == 1 and 3 <= len(polys[0]) <= MAX_POINTS
    xs = [p[0] for p in polys[0]]
    assert 30 <= min(xs) <= 45 and 210 <= max(xs) <= 225
    assert mask_outlines(np.zeros((10, 10), bool)) == []


def test_anatomy_refused_before_submit_then_served(api_env):
    c = api_env()
    _, n = _practice(c)
    aid = n["attempt_id"]
    r = c.get(f"/api/attempts/{aid}/anatomy")
    assert r.status_code == 409 and "polygons" not in r.text
    assert c.get("/api/attempts/nope/anatomy").status_code == 404
    assert c.post(f"/api/attempts/{aid}/submit", json=_body(declared_normal=True)).status_code == 200
    a = c.get(f"/api/attempts/{aid}/anatomy").json()
    ids = {z["id"] for z in a["zones"]}
    assert {"right_upper_zone", "left_upper_zone"} <= ids and "lungs" not in ids
    assert all(3 <= len(p) <= MAX_POINTS for z in a["zones"] for p in z["polygons"])
    assert isinstance(a["midline_x"], float) and isinstance(a["approximate"], bool)
    # patient-side convention: right_* zones sit on the image LEFT of the midline
    ru = next(z for z in a["zones"] if z["id"] == "right_upper_zone")
    assert np.mean([p[0] for p in ru["polygons"][0]]) < a["midline_x"]


def test_anatomy_refused_in_assessment_until_summary(api_env, processed_copy):
    ids = ["syn_001", "syn_008"]
    resplit(processed_copy, {i: "assess_A" for i in ids})
    c = api_env(processed_copy)
    s = c.post("/api/sessions", json={"display_name": "A", "level": "MS3", "mode": "assess_A"}).json()
    aids = []
    for _ in ids:
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        assert c.get(f"/api/attempts/{n['attempt_id']}/anatomy").status_code == 409
        assert c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True)).status_code == 200
        aids.append(n["attempt_id"])
        if len(aids) < len(ids):
            assert c.get(f"/api/attempts/{aids[0]}/anatomy").status_code == 409  # submitted, summary not ready
    summ = c.get(f"/api/sessions/{s['session_id']}/summary").json()
    assert (summ["n_abnormal"], summ["n_normal"], summ["n_focal_findings"]) == (1, 1, 1)
    assert c.get(f"/api/attempts/{aids[0]}/anatomy").status_code == 200


# ------------------------------------------------------------------ review geometry + cohort
def test_review_items_carry_geometry(api_env):
    c = api_env()
    _, n = _practice(c)
    cid = n["case"]["case_id"]
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(marks=[mark("M1", 10, 10, "nodule")]))
    c.post(f"/api/attempts/{n['attempt_id']}/flag", json={"comment": "check"})
    items = c.get("/api/review/items").json()["items"]
    live = [i for i in items if i["origin"] == "live"]
    assert live, items
    it = live[0]
    assert it["case_id"] == cid and it["flagged"] is True
    assert it["image_url"] == f"/api/cases/{cid}/image" and it["width"] == 256 and it["height"] == 256
    assert it["learner"]["marks"][0]["mark_id"] == "M1"
    for f in it["findings"]:
        assert f["finding_id"].startswith("F") and "#" not in f["finding_id"]
        assert {"label", "display", "kind", "polygon", "bbox", "centroid", "side", "primary_zone"} <= set(f)
        assert len(f["bbox"]) == 4 and len(f["centroid"]) == 2


def test_cohort_learning_curve_pure():
    def rec(lid, t, ok):
        return {
            "learner_id": lid,
            "submitted_at": t,
            "success": ok,
            "score": 0,
            "outcomes": [],
            "findings": [],
            "is_normal": True,
        }

    recs = [rec("a", "1", True), rec("a", "2", False), rec("b", "1", False), rec("a", "3", True)]
    lc = cohort_learning_curve(recs, window=10)
    assert lc[0] == {"index": 1, "accuracy": 0.5, "n": 2}  # a: 1.0, b: 0.0
    assert lc[1] == {"index": 2, "accuracy": 0.5, "n": 1}  # a: 1/2
    assert lc[2]["n"] == 1 and lc[2]["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert cohort_learning_curve([]) == []


def test_cohort_dashboard_has_learning_curve_and_level(api_env):
    c = api_env()
    s, n = _practice(c)
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True))
    d = c.get("/api/cohort/dashboard").json()
    assert d["learning_curve"] == [{"index": 1, "accuracy": d["learning_curve"][0]["accuracy"], "n": 1}]
    assert d["learners"][0]["level"] == "MS3"


def test_root_dockerfile_matches_deploy_copy():
    """Hugging Face builds /Dockerfile; deploy/Dockerfile is the canonical copy (keep in sync)."""
    from backend.app.settings import REPO_ROOT

    root, canon = REPO_ROOT / "Dockerfile", REPO_ROOT / "deploy" / "Dockerfile"
    if not canon.exists():
        pytest.skip("no deploy/Dockerfile")
    assert root.read_text() == canon.read_text()
    assert "--extra ml" not in canon.read_text() and "7860" in canon.read_text()
