"""Versioned prompt files in backend/app/prompts/ (first line: `<!-- prompt: name | version: vN | ... -->`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from backend.app.tutor import vocab

_HEADER = re.compile(r"^<!--\s*prompt:\s*(?P<name>[\w-]+)\s*\|\s*version:\s*(?P<version>[\w.-]+).*-->\s*$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


@lru_cache
def load_prompt(name: str) -> Prompt:
    raw = (vocab.PROMPTS_DIR / f"{name}.md").read_text()
    first, _, body = raw.partition("\n")
    m = _HEADER.match(first.strip())
    if not m:
        raise ValueError(f"prompts/{name}.md is missing its version header")
    return Prompt(name=m["name"], version=m["version"], text=body.strip() + "\n")
