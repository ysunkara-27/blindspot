"""Claude client for debriefs and ask-the-tutor (SPEC §8.5).

Request shape (verified against anthropic SDK 1.11.0, `messages.create`):
  system = [{text: <prompt>}, {text: <all cards + zone mimics>, cache_control: ephemeral}]
  messages = [user: 3 base64 PNG images + "FACTS:\n<json>"]
  output_config = {"format": {"type": "json_schema", "schema": <constant schema>}, "effort": <low by default>}
Timeout 12 s, one retry on 5xx / overloaded / connection errors (not on timeouts), then the caller falls back to a
template. Model ids come from settings (env); never hard-coded. Unit tests use MockClient — never the network.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from backend.app.settings import get_settings
from backend.app.tutor import vocab

TIMEOUT_S = 12.0
# Debrief output cap. The prompt targets ~110 words (~350 output tokens incl. JSON keys and low-effort adaptive
# thinking, which counts against max_tokens). Base 700 per the 2026-10-05 smoke review. Prompt v3 requires a sign and
# a full `why` sentence for EVERY finding (~25 words ≈ 90 tokens with JSON keys per row), so each finding beyond 2
# adds 90 tokens and the ceiling covers the validator's crowded-film word limit (a max_tokens stop falls back to the
# template). eval/adapters reads the base.
DEBRIEF_MAX_TOKENS = 700
DEBRIEF_MAX_TOKENS_PER_EXTRA_FINDING = 90
DEBRIEF_MAX_TOKENS_CEILING = 4000


def debrief_max_tokens(n_findings: int) -> int:
    extra = DEBRIEF_MAX_TOKENS_PER_EXTRA_FINDING * max(0, int(n_findings) - 2)
    return min(DEBRIEF_MAX_TOKENS_CEILING, DEBRIEF_MAX_TOKENS + extra)


ASK_MAX_TOKENS = 600
# Effort for runtime calls (latency). "none" omits the parameter for models without effort support.
DEFAULT_EFFORT = "low"
LOCAL_LIMITER = "BLINDSPOT_MAX_LIVE_CALLS_PER_MIN reached"  # LiveCallError.detail of the in-process limiter
_SCHEMA_META_KEYS = ("$schema", "$id", "title", "description")

ASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}


@lru_cache
def debrief_schema() -> dict[str, Any]:
    """shared/schemas/debrief_output.json minus annotation keys. Constant across calls (keeps caches valid)."""
    doc = json.loads((vocab.SCHEMAS_DIR / "debrief_output.json").read_text())
    return {k: v for k, v in doc.items() if k not in _SCHEMA_META_KEYS}


class LiveCallError(Exception):
    """A live call that produced no usable text.

    kind: timeout | api | rate_limited | refusal | max_tokens | empty | credits_depleted | auth | unavailable |
    budget_exceeded. `paused` is True when the tutor guard skipped the network (backend/app/tutor/guard.py)."""

    def __init__(self, kind: str, detail: str = "", *, paused: bool = False) -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail
        self.paused = paused

    @property
    def reason(self) -> str:
        """validator["fallback_reason"]: live_<kind> for a failed call, paused_<kind> for a skipped one."""
        return f"{'paused' if self.paused else 'live'}_{self.kind}"


# DebriefResponse.error codes (PROGRESS.md `TUTOR ERRORS`; the frontend keys its copy on these).
ERROR_CODES = (
    "offline",
    "credits_depleted",
    "rate_limited",
    "budget_exceeded",
    "unavailable",
    "auth",
    "validator_failed",
    "timeout",
    "internal_error",
)
# LiveCallError.kind -> error code.
KIND_ERRORS: dict[str, str] = {
    "timeout": "timeout",
    "api": "unavailable",
    "unavailable": "unavailable",
    "rate_limited": "rate_limited",
    "credits_depleted": "credits_depleted",
    "budget_exceeded": "budget_exceeded",
    "auth": "auth",
    "refusal": "validator_failed",
    "max_tokens": "validator_failed",
    "empty": "validator_failed",
}
# Template fallback reason (validator["fallback_reason"]) -> short `error` code for the UI ("The tutor is busy/offline.
# Showing the built-in explanation instead."). live_<kind>: the call failed; paused_<kind>: the guard skipped it.
FALLBACK_ERRORS: dict[str, str] = {
    "offline": "offline",
    "no_api_key": "offline",
    "bad_json": "validator_failed",
    "validator_failed": "validator_failed",
    "internal_error": "internal_error",
    **{f"live_{k}": v for k, v in KIND_ERRORS.items()},
    **{f"paused_{k}": v for k, v in KIND_ERRORS.items()},
}


def fallback_error(reason: str | None) -> str:
    """Error code for a template fallback reason (unknown reasons -> internal_error)."""
    return FALLBACK_ERRORS.get(reason or "", "internal_error")


_CREDIT_WORDS = ("credit balance", "billing", "too low", "insufficient credit", "purchase credits")


def classify_status_error(status_code: int, message: str) -> str:
    """LiveCallError.kind for an HTTP error from the API.

    402, or 400/403 whose message mentions the credit balance / billing / "too low" -> credits_depleted;
    401 -> auth; 429 -> rate_limited; 5xx (incl. 529 overloaded) -> unavailable; other 4xx -> api."""
    m = (message or "").lower()
    if status_code == 402 or (status_code in (400, 403) and any(w in m for w in _CREDIT_WORDS)):
        return "credits_depleted"
    if status_code == 401:
        return "auth"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "unavailable"
    return "api"


def classify_exception(e: BaseException) -> str:
    """LiveCallError.kind for an anthropic SDK exception (timeouts and connection errors included)."""
    import anthropic

    if isinstance(e, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(e, anthropic.APIStatusError):
        body = getattr(e, "body", None)
        text = f"{getattr(e, 'message', '') or e} {json.dumps(body) if isinstance(body, dict | list) else body or ''}"
        return classify_status_error(int(getattr(e, "status_code", 0) or 0), text)
    if isinstance(e, anthropic.APIConnectionError):
        return "unavailable"
    return "api"


@dataclass
class LLMResponse:
    text: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    stop_reason: str | None = None
    latency_ms: float = 0.0
    cost_usd: float | None = None  # set by guard.guarded_complete from the token counts and env prices


class TutorClient(Protocol):
    model: str | None

    def complete(
        self, *, system: list[dict[str, Any]], messages: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int
    ) -> LLMResponse: ...


class RateLimiter:
    """Sliding one-minute window, process-wide (SPEC §2.4 BLINDSPOT_MAX_LIVE_CALLS_PER_MIN)."""

    def __init__(self, per_min: int) -> None:
        self.per_min = max(0, int(per_min))
        self._t: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            while self._t and now - self._t[0] >= 60.0:
                self._t.popleft()
            if len(self._t) >= self.per_min:
                return False
            self._t.append(now)
            return True


_LIMITER: RateLimiter | None = None


def _limiter() -> RateLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RateLimiter(get_settings().blindspot_max_live_calls_per_min)
    return _LIMITER


def image_block(png: bytes) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()},
    }


def system_blocks(prompt_text: str, cards_text: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": prompt_text},
        {"type": "text", "text": cards_text, "cache_control": {"type": "ephemeral"}},
    ]


def user_content(images: Sequence[bytes] | None, text: str) -> list[dict[str, Any]]:
    return [image_block(p) for p in (images or [])] + [{"type": "text", "text": text}]


class AnthropicTutorClient:
    """Wraps anthropic.Anthropic().messages.create. `sdk_client` lets callers inject an Anthropic-like object."""

    def __init__(
        self,
        model: str | None = None,
        *,
        timeout: float = TIMEOUT_S,
        effort: str | None = None,
        sdk_client: Any | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        s = get_settings()
        self.model = model or s.blindspot_model_debrief
        self.timeout = timeout
        eff = effort or os.environ.get("BLINDSPOT_TUTOR_EFFORT", DEFAULT_EFFORT)
        self.effort = None if eff in ("", "none") else eff
        self._sdk = sdk_client
        self._limiter = limiter

    def _client(self) -> Any:
        if self._sdk is None:
            import anthropic

            key = get_settings().anthropic_api_key
            self._sdk = anthropic.Anthropic(api_key=key, timeout=self.timeout, max_retries=0)
        return self._sdk

    def complete(
        self, *, system: list[dict[str, Any]], messages: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int
    ) -> LLMResponse:
        import anthropic

        if not (self._limiter or _limiter()).try_acquire():
            raise LiveCallError("rate_limited", LOCAL_LIMITER)
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        kwargs = dict(
            model=self.model, max_tokens=max_tokens, system=system, messages=messages, output_config=output_config
        )
        t0 = time.perf_counter()
        resp = None
        for attempt in range(2):
            try:
                resp = self._client().messages.create(**kwargs)
                break
            except anthropic.APIError as e:
                kind = classify_exception(e)
                # one retry on 5xx / overloaded / connection errors (never on timeouts, 4xx, credits, auth)
                if kind == "unavailable" and attempt == 0:
                    continue
                status = getattr(e, "status_code", None)
                raise LiveCallError(kind, f"{type(e).__name__}{f' {status}' if status else ''}") from e
        latency = (time.perf_counter() - t0) * 1000.0
        if resp is None:  # pragma: no cover - loop always breaks or raises
            raise LiveCallError("api", "no response")
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            raise LiveCallError("refusal", str(getattr(resp, "stop_details", "") or ""))
        if stop == "max_tokens":
            raise LiveCallError("max_tokens")
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
        if not text.strip():
            raise LiveCallError("empty")
        u = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            model=getattr(resp, "model", self.model),
            input_tokens=getattr(u, "input_tokens", None),
            output_tokens=getattr(u, "output_tokens", None),
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", None),
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", None),
            stop_reason=stop,
            latency_ms=latency,
        )


@dataclass
class MockClient:
    """Test double: returns canned responses in order (str/dict → JSON text; Exception → raised)."""

    responses: list[Any]
    model: str | None = "mock-model"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self, *, system: list[dict[str, Any]], messages: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "schema": schema, "max_tokens": max_tokens})
        if not self.responses:
            raise LiveCallError("api", "MockClient has no responses left")
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        if isinstance(r, LLMResponse):
            return r
        text = r if isinstance(r, str) else json.dumps(r)
        return LLMResponse(text=text, model=self.model, input_tokens=100, output_tokens=50, latency_ms=1.0)


def as_tutor_client(client: Any | None, model: str | None = None) -> TutorClient | None:
    """Accept our TutorClient, an Anthropic-like SDK client (has .messages.create), or None."""
    if client is None:
        return None
    if hasattr(client, "complete"):
        return client
    if hasattr(client, "messages") and hasattr(client.messages, "create"):
        return AnthropicTutorClient(model=model, sdk_client=client)
    raise TypeError(f"unsupported tutor client: {type(client).__name__}")
