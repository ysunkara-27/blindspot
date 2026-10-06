"""tutor_bridge hint wiring: the hint log reaches tutor.hints as `previous`; the fallback never reveals normal vs
abnormal (QA #8). Synthetic fixtures; offline."""

from __future__ import annotations

import types

from backend.app import tutor_bridge
from backend.app.tests.conftest import hover


def test_fallback_hint_is_identical_for_normal_and_abnormal_films(repo, monkeypatch):
    normal, abnormal = repo.get("syn_008"), repo.get("syn_001")
    tel = hover(60, 60, 1500)
    for level in (1, 2, 3):
        texts = []
        for case in (normal, abnormal):
            zones, _ = repo.zones(case.case_id)
            texts.append(tutor_bridge.fallback_hint(level, case, [], tel, zones))
        assert texts[0] == texts[1], (level, texts)
        assert "normal" not in texts[0].lower() and "asymmetry" not in texts[0].lower()
    # the fallback is what /hint serves when the tutor module is missing
    monkeypatch.setattr(tutor_bridge, "_mod", lambda name: None)
    zones, _ = repo.zones("syn_008")
    assert tutor_bridge.hint(2, normal, [], [], zones) == tutor_bridge.fallback_hint(1, normal, [], [], zones)


def test_hint_route_passes_hint_log_as_previous(api_env, monkeypatch):
    seen: list = []

    def fake_hint(level, case, marks, telemetry, zones, *, previous=None):
        seen.append(list(previous or []))
        return f"hint {level}"

    real_mod = tutor_bridge._mod
    monkeypatch.setattr(
        tutor_bridge, "_mod", lambda name: types.SimpleNamespace(hint=fake_hint) if name == "hints" else real_mod(name)
    )
    c = api_env()
    s = c.post("/api/sessions", json={"display_name": "H", "level": "MS3", "mode": "practice"}).json()
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    for _ in range(3):
        assert c.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []}).status_code == 200
    assert [len(p) for p in seen] == [0, 1, 2]
    assert [p["text"] for p in seen[2]] == ["hint 1", "hint 2"] and seen[2][1]["level"] == 2
