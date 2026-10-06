"""Loaded before any backend test module: hosting gates and the base path must never leak from the developer's
.env into unit tests (environment variables beat .env in pydantic-settings)."""

import os

for _k in ("BLINDSPOT_ACCESS_CODE", "BLINDSPOT_REVIEW_CODE", "BLINDSPOT_BASE_PATH"):
    os.environ[_k] = ""
for _k in ("BLINDSPOT_SERVE_FRONTEND", "BLINDSPOT_DEV"):
    os.environ[_k] = "0"
os.environ["BLINDSPOT_OFFLINE"] = "1"
os.environ["BLINDSPOT_ANALYTICS_URL"] = ""
# Unit tests never touch the developer's database (tutor guard persistence, spend queries).
import tempfile as _tempfile  # noqa: E402

os.environ.setdefault("BLINDSPOT_DB_PATH", os.path.join(_tempfile.mkdtemp(prefix="blindspot-tests-"), "unit.sqlite"))
