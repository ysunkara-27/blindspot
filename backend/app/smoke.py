"""Smoke test of the API flow: create session → next → submit (scripted telemetry) → debrief poll → next.

Usage:
  uv run python -m backend.app.smoke                      # in-process TestClient against the synthetic fixtures
  uv run python -m backend.app.smoke --base http://127.0.0.1:8000   # against a running server
No Anthropic calls: in-process mode forces BLINDSPOT_OFFLINE=1 and a temp DB.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[2] / "pipeline" / "tests" / "fixtures" / "synthetic"


def scripted_telemetry(w: int, h: int, focus: tuple[float, float] | None) -> list[dict[str, Any]]:
    """A short raster over the image, then 1.2 s hovering near `focus` (image px)."""
    ev, t = [], 0.0
    for row in range(1, 6):
        y = h * row / 6
        for k in range(30):
            ev.append(
                {
                    "t": t,
                    "kind": "move",
                    "x": w * (0.1 + 0.8 * k / 29),
                    "y": y,
                    "zoom": 1.0,
                    "vp": [0, 0, w, h],
                    "loupe": True,
                }
            )
            t += 33
    if focus:
        for k in range(36):
            ev.append(
                {
                    "t": t,
                    "kind": "move",
                    "x": focus[0] + (2 if k % 2 else -2),
                    "y": focus[1],
                    "zoom": 2.5,
                    "vp": [focus[0] - w / 5, focus[1] - h / 5, focus[0] + w / 5, focus[1] + h / 5],
                    "loupe": True,
                }
            )
            t += 33
    ev.append({"t": t, "kind": "leave", "x": None, "y": None, "zoom": 1.0, "vp": [0, 0, w, h], "loupe": True})
    return ev


def run(client: Any, n_cases: int = 3) -> int:
    def call(method: str, path: str, **kw) -> Any:
        r = getattr(client, method)(path, **kw)
        if r.status_code >= 400:
            raise SystemExit(f"{method.upper()} {path} → {r.status_code}: {r.text[:300]}")
        return r.json()

    print("health:", call("get", "/api/health"))
    s = call("post", "/api/sessions", json={"display_name": "Smoke", "level": "MS2", "mode": "practice"})
    print("session:", s)
    for i in range(n_cases):
        n = call("get", f"/api/sessions/{s['session_id']}/next")
        cid, w, h = n["case"]["case_id"], n["case"]["width"], n["case"]["height"]
        print(f"\n[{i + 1}] next → attempt {n['attempt_id'][:8]} case {cid} ({w}×{h})")
        img = client.get(n["case"]["image_url"])
        print(f"    image: {img.status_code} {img.headers.get('content-type')} {len(img.content)} bytes")
        hint = call("post", f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []})
        print(f"    hint {hint['level']}: {hint['text']}")
        mark = {"mark_id": "M1", "x": w * 0.27, "y": h * 0.58, "label": "nodule", "confidence": 3}
        body = {
            "marks": [mark],
            "patterns": [],
            "declared_normal": False,
            "telemetry": scripted_telemetry(w, h, (mark["x"], mark["y"])),
            "hints_used": 1,
            "client_timing": {"shown_at": "2026-10-05T21:00:00Z", "submitted_at": "2026-10-05T21:00:25Z"},
        }
        r = call("post", f"/api/attempts/{n['attempt_id']}/submit", json=body)
        print(f"    submit: score {r['score']} success {r['success']} debrief {r['debrief_status']}")
        print("    outcomes:", [(o["target"], o["result"], o.get("dwell_ms")) for o in r["outcomes"]])
        print("    facts card:", r["facts_card"]["headline"])
        for line in r["facts_card"]["lines"]:
            print("      -", line)
        for a in r["reveal"]["arrows"]:
            print("    arrow:", a["text"])
        print(
            f"    search: lung coverage {r['reveal']['search']['lung_coverage_pct']}%, "
            f"unvisited {r['reveal']['search']['unvisited_review_areas']}"
        )
        d: dict = {}
        for _ in range(40):
            d = call("get", f"/api/attempts/{n['attempt_id']}/debrief")
            if d["status"] != "pending":
                break
            time.sleep(0.25)
        print(
            f"    debrief: status {d['status']} source {d.get('source')} "
            f"{(d.get('debrief') or {}).get('headline') or d.get('error') or ''}"
        )
    dash = call("get", f"/api/learners/{s['learner_id']}/dashboard")
    print(f"\ndashboard: n={dash['n_attempts']} summary={json.dumps(dash['summary'])}")
    print("SMOKE OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="base URL of a running API (default: in-process on fixtures)")
    ap.add_argument("--cases", type=int, default=3)
    a = ap.parse_args()
    if a.base:
        import httpx

        return run(httpx.Client(base_url=a.base, timeout=30), a.cases)
    tmp = tempfile.mkdtemp(prefix="blindspot_smoke_")
    os.environ.setdefault("BLINDSPOT_PROCESSED_DIR", str(FIXTURES))
    os.environ["BLINDSPOT_DB_PATH"] = str(Path(tmp) / "smoke.sqlite")
    os.environ["BLINDSPOT_OFFLINE"] = "1"
    from fastapi.testclient import TestClient

    from backend.app.main import app

    return run(TestClient(app), a.cases)


if __name__ == "__main__":
    sys.exit(main())
