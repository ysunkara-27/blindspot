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
    def offline(self) -> bool:
        return self.blindspot_offline or not self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
