"""Eval tests never reach the network: constructing an Anthropic client raises (CLAUDE.md rule 5)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("eval tests must not construct an Anthropic client (no live API calls)")

    monkeypatch.setattr(anthropic.Anthropic, "__init__", boom)
    monkeypatch.setenv("BLINDSPOT_OFFLINE", "1")


@pytest.fixture
def fixture_args(tmp_path):  # noqa: ANN001, ANN201
    """Common CLI args that keep every output in tmp and force the synthetic fixtures."""
    return [
        "--dry-run",
        "--source",
        "fixtures",
        "--out-dir",
        str(tmp_path / "reports"),
        "--cache-dir",
        str(tmp_path / "cache"),
    ]
