"""OpenAPI ↔ shared/schemas contract: routes use the shared.contracts models, OpenAPI component properties match
the JSON Schemas, and live responses validate against the JSON Schemas."""

from __future__ import annotations

import json
import typing

import pytest

from backend.app.tests.conftest import chain, hover, make_submit, mark
from backend.app.tests.routes_util import iter_api_routes
from shared import contracts as c
from shared.tests.test_contracts import SCHEMAS, _validator

ROUTE_MODELS = {
    ("POST", "/api/sessions"): c.SessionCreated,
    ("GET", "/api/sessions/{sid}/next"): c.NextCase,
    ("GET", "/api/sessions/{sid}/summary"): c.AssessmentSummary,
    ("POST", "/api/attempts/{aid}/hint"): c.HintResponse,
    ("GET", "/api/attempts/{aid}/debrief"): c.DebriefResponse,
    ("POST", "/api/attempts/{aid}/ask"): c.AskResponse,
    ("POST", "/api/sus"): c.SusResult,
    ("GET", "/api/health"): c.Health,
}
REQUEST_MODELS = {
    ("POST", "/api/sessions"): c.SessionCreate,
    ("POST", "/api/attempts/{aid}/hint"): c.HintRequest,
    ("POST", "/api/attempts/{aid}/submit"): c.AttemptSubmit,
    ("POST", "/api/attempts/{aid}/ask"): c.AskRequest,
    ("POST", "/api/review/ratings"): c.ReviewRating,
    ("POST", "/api/sus"): c.SusSubmit,
}


def _routes(app):
    out = {}
    for path, r in iter_api_routes(app):
        for m in r.methods:
            out[(m, path)] = r
    return out


def _schema_props() -> dict[str, set[str]]:
    """name → property names, from every top-level schema (by title) and every $defs entry."""
    out: dict[str, set[str]] = {}
    for f in SCHEMAS.glob("*.json"):
        doc = json.loads(f.read_text())
        if "properties" in doc:
            out[doc["title"]] = set(doc["properties"])
        for name, d in doc.get("$defs", {}).items():
            if "properties" in d:
                out[name] = set(d["properties"])
    return out


def test_routes_use_shared_contract_models(api_env):
    routes = _routes(api_env().app)
    for key, model in ROUTE_MODELS.items():
        assert key in routes, key
        assert routes[key].response_model is model, key
    sub = routes[("POST", "/api/attempts/{aid}/submit")].response_model
    assert set(getattr(sub, "__args__", ())) == {c.SubmitResult, c.AssessmentRecorded}
    for key, model in REQUEST_MODELS.items():
        hints = typing.get_type_hints(routes[key].endpoint)
        assert hints.get("body") is model, key


def test_openapi_components_match_json_schemas(api_env):
    spec = api_env().get("/api/openapi.json").json()
    comps = spec["components"]["schemas"]
    props = _schema_props()
    checked = 0
    for name, sch in comps.items():
        base = name.removesuffix("-Input").removesuffix("-Output")
        if base in props and "properties" in sch:
            assert set(sch["properties"]) == props[base], name
            checked += 1
    for must in (
        "SubmitResult",
        "Outcome",
        "RevealFinding",
        "SearchSummary",
        "NextCase",
        "DebriefResponse",
        "AttemptSubmit",
        "TelemetryEvent",
        "HintResponse",
        "SessionCreated",
        "AssessmentSummary",
    ):
        assert any(n.removesuffix("-Input").removesuffix("-Output") == must for n in comps), must
    assert checked >= 15


def _check(data, schema, pointer=None):
    errs = sorted(_validator(schema, pointer).iter_errors(data), key=str)
    assert not errs, "\n".join(e.message for e in errs[:5])


@pytest.fixture
def flow(api_env):
    cl = api_env()
    s = cl.post("/api/sessions", json={"display_name": "C", "level": "MS1", "mode": "practice"}).json()
    return cl, s


def test_live_responses_validate_against_json_schemas(flow):
    cl, s = flow
    _check(cl.get("/api/health").json(), "api.json", "/$defs/Health")
    _check(s, "api.json", "/$defs/SessionCreated")
    for _ in range(4):
        n = cl.get(f"/api/sessions/{s['session_id']}/next").json()
        _check(n, "api.json", "/$defs/NextCase")
        h = cl.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []}).json()
        _check(h, "api.json", "/$defs/HintResponse")
        body = json.loads(
            make_submit(
                marks=[mark("M1", 70, 150, "nodule"), mark("M2", 185, 60, "mass", 2)],
                telemetry=chain(hover(70, 150, 600), hover(185, 60, 400)),
            ).model_dump_json()
        )
        r = cl.post(f"/api/attempts/{n['attempt_id']}/submit", json=body).json()
        _check(r, "submit_result.json")
        d = cl.get(f"/api/attempts/{n['attempt_id']}/debrief").json()
        _check(d, "debrief_response.json")
        a = cl.post(f"/api/attempts/{n['attempt_id']}/ask", json={"question": "Why?"}).json()
        _check(a, "api.json", "/$defs/AskResponse")
    _check(cl.get(f"/api/sessions/{s['session_id']}/summary").json(), "api.json", "/$defs/AssessmentSummary")
    _check(
        cl.post("/api/sus", json={"learner_id": s["learner_id"], "answers": [3] * 10}).json(),
        "api.json",
        "/$defs/SusResult",
    )
