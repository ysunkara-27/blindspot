"""Runtime settings. Model IDs come from env vars (never hard-coded in app code)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    blindspot_model_debrief: str = "claude-sonnet-5-5"
    blindspot_model_fast: str = "claude-haiku-4-5-20251001"
    blindspot_model_judge: str = "claude-opus-5-5"
    blindspot_model_bench: str = "claude-sonnet-5-5"
    blindspot_data_dir: Path = Path("./data")
    blindspot_db_path: Path = Path("./data/blindspot.sqlite")
    blindspot_offline: bool = False
    blindspot_max_live_calls_per_min: int = 30
    # /api/dev/* (clinical-QA overlays; exposes ground truth). Off by default; BLINDSPOT_DEV=1 enables.
    blindspot_dev: bool = False
    # Hosting (deploy/README.md). Unset = local dev: nothing gated, served at /api and (optionally) /.
    blindspot_access_code: str | None = None  # every /api route except health/about/access needs it
    blindspot_review_code: str | None = None  # /api/review/* and /api/cohort/* additionally need it
    blindspot_base_path: str = ""  # e.g. "/blindspot" -> API at /blindspot/api/..., SPA at /blindspot/
    blindspot_serve_frontend: bool = False  # serve frontend/dist (built with VITE_BASE_PATH) with SPA fallback
    blindspot_frontend_dist: Path = Path("./frontend/dist")
    blindspot_cors_origins: str = ""  # comma list, added to the Vite dev origins

    @property
    def data_dir(self) -> Path:
        p = self.blindspot_data_dir
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def db_path(self) -> Path:
        p = self.blindspot_db_path
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def config_dir(self) -> Path:
        return REPO_ROOT / "config"

    @property
    def base_path(self) -> str:
        """Normalised base path: "" or "/segment" (leading slash, no trailing slash)."""
        b = (self.blindspot_base_path or "").strip().strip("/")
        return f"/{b}" if b else ""

    @property
    def api_prefix(self) -> str:
        """Public URL prefix of the API, used for URLs the API hands out (e.g. image_url)."""
        return f"{self.base_path}/api"

    @property
    def frontend_dist(self) -> Path:
        p = self.blindspot_frontend_dist
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.blindspot_cors_origins.split(",") if o.strip()]

    @property
    def access_code(self) -> str | None:
        return (self.blindspot_access_code or "").strip() or None

    @property
    def review_code(self) -> str | None:
        return (self.blindspot_review_code or "").strip() or None

    @property
    def offline(self) -> bool:
        return self.blindspot_offline or not self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
