"""Container entrypoint (deploy/Dockerfile): fetch data if missing → ensure the SQLite schema → exec uvicorn.

1. If `$BLINDSPOT_DATA_DIR/processed/cases.jsonl` is missing, download the processed-data bundle from the PRIVATE
   Hugging Face dataset repo `$BLINDSPOT_DATA_REPO` (made by deploy/make_data_bundle.py --upload) with `$HF_TOKEN`
   into `$BLINDSPOT_DATA_DIR/processed`. The image itself never contains dataset files.
2. Create the SQLite schema at `$BLINDSPOT_DB_PATH` (default /data/blindspot.sqlite). Without a persistent volume
   it starts empty on every restart; that is expected for the demo.
3. Optional: `BLINDSPOT_SEED_DEMO=1` seeds the demo learner + playlist (offline templates; no API call).
4. exec uvicorn on 0.0.0.0:$PORT (7860 on Hugging Face), trusting X-Forwarded-* from the proxy.

Never prints secrets (HF_TOKEN, ANTHROPIC_API_KEY, access codes).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]


def log(msg: str) -> None:
    print(f"[entrypoint] {msg}", flush=True)


def data_dir() -> Path:
    p = Path(os.environ.get("BLINDSPOT_DATA_DIR", "/data"))
    return p if p.is_absolute() else (APP_DIR / p).resolve()


def has_data(processed: Path) -> bool:
    return (processed / "cases.jsonl").is_file() and (processed / "images").is_dir()


def fetch_data(processed: Path) -> None:
    repo = os.environ.get("BLINDSPOT_DATA_REPO", "").strip()
    if not repo:
        log("BLINDSPOT_DATA_REPO is not set and no data is mounted; the API will start with 0 cases.")
        return
    token = os.environ.get("HF_TOKEN") or None
    from huggingface_hub import snapshot_download

    processed.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log(f"downloading dataset repo {repo} into {processed} (private; token {'set' if token else 'NOT set'})")
    snapshot_download(
        repo_id=repo,
        repo_type="dataset",
        local_dir=str(processed),
        token=token,
        max_workers=8,
        allow_patterns=[
            "cases.jsonl",
            "cases_msd.jsonl",
            "splits.json",
            "*.json",
            "images/*",
            "masks/*",
            "zones/*",
            "volumes/*",
            "zones3d/*",
            "previews/*",
        ],
    )
    n = sum(1 for _ in (processed / "cases.jsonl").open()) if (processed / "cases.jsonl").exists() else 0
    log(f"data ready: {n} cases in {time.time() - t0:.0f} s")


def ensure_db() -> None:
    subprocess.run([sys.executable, "-m", "backend.app.db"], cwd=APP_DIR, check=True)
    if os.environ.get("BLINDSPOT_SEED_DEMO", "").strip() in ("1", "true", "yes"):
        env = dict(os.environ, BLINDSPOT_OFFLINE="1")  # seeding never makes live calls
        r = subprocess.run([sys.executable, "-m", "backend.app.demo_seed"], cwd=APP_DIR, env=env)
        log(f"demo seed exit code {r.returncode}")


def main() -> None:
    processed = data_dir() / "processed"
    if not has_data(processed):
        try:
            fetch_data(processed)
        except Exception as e:  # noqa: BLE001 — start anyway; /api/health reports cases=0
            log(f"data download failed: {type(e).__name__}: {e}")
    else:
        log(f"data present at {processed}")
    ensure_db()
    port = os.environ.get("PORT", "7860")
    log(f"starting uvicorn on :{port} base={os.environ.get('BLINDSPOT_BASE_PATH', '') or '/'}")
    os.chdir(APP_DIR)
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            os.environ.get("HOST", "0.0.0.0"),
            "--port",
            port,
            "--proxy-headers",
            "--forwarded-allow-ips",
            "*",
            "--workers",
            os.environ.get("WEB_CONCURRENCY", "1"),
        ],
    )


if __name__ == "__main__":
    main()
