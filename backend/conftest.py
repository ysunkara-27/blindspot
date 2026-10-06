"""Loaded before any backend test module: hosting gates and the base path must never leak from the developer's
.env into unit tests (environment variables beat .env in pydantic-settings)."""

import os

for _k in ("BLINDSPOT_ACCESS_CODE", "BLINDSPOT_REVIEW_CODE", "BLINDSPOT_BASE_PATH"):
    os.environ[_k] = ""
for _k in ("BLINDSPOT_SERVE_FRONTEND", "BLINDSPOT_DEV"):
    os.environ[_k] = "0"
os.environ["BLINDSPOT_OFFLINE"] = "1"
