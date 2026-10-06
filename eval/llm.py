"""Structured-output Claude calls for the eval scripts, with a response cache, mocks, and spend tracking.

- Live calls use the official SDK: client.messages.create(..., output_config={"format": {"type": "json_schema",
  "schema": ...}}). Thinking is left at the model default (adaptive on current models); `effort` is optional.
- No server-side model fallbacks: a refusal is recorded as a refusal, so every result is attributable to the
  model under test (a fallback would silently benchmark a different model).
- Cache key = sha256(model, every non-image request part, image sha256s). Mocks live in a separate namespace.
- `CachingAnthropic` is a duck-typed client injected into the production tutor service so the faithfulness eval
  runs the real pipeline while every request is cached, costed, and logged here.
"""

from __future__ import annotations

import base64
import copy
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from eval.common import ResponseCache, SpendTracker, cache_key, canonical_json, sha256_bytes, text_tokens

MockFn = Callable[[dict[str, Any], Any], dict[str, Any]]


@dataclass
class LLMResult:
    key: str
    parsed: dict[str, Any] | None
    text: str | None
    stop_reason: str | None
    usage: dict[str, Any]
    model: str
    cached: bool = False
    mock: bool = False
    error: str | None = None
    latency_ms: float | None = None

    @property
    def ok(self) -> bool:
        return self.parsed is not None and self.error is None


def strip_images(obj: Any) -> tuple[Any, list[str]]:
    """Deep-copy a request with base64 image data replaced by its sha256 (for cache keys and logs)."""
    hashes: list[str] = []

    def walk(o: Any) -> Any:
        if isinstance(o, dict):
            if o.get("type") == "base64" and "data" in o:
                h = sha256_bytes(base64.b64decode(o["data"]) if isinstance(o["data"], str) else bytes(o["data"]))
                hashes.append(h)
                return {**{k: v for k, v in o.items() if k != "data"}, "data_sha256": h}
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if hasattr(o, "model_dump"):
            return walk(o.model_dump(mode="json"))
        return o

    return walk(copy.deepcopy(obj) if not hasattr(obj, "model_dump") else obj), hashes


def request_key(kwargs: dict[str, Any]) -> str:
    prompt, hashes = strip_images({k: v for k, v in kwargs.items() if k not in ("model", "timeout")})
    return cache_key(kwargs["model"], prompt, hashes)


def png_dims(b64: str) -> tuple[int, int] | None:
    """Width/height from a base64 PNG's IHDR chunk (no decode of the pixel data)."""
    try:
        head = base64.b64decode(b64[:64])
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except (ValueError, IndexError):
        return None


def _image_dims(obj: Any) -> list[tuple[int, int] | None]:
    out: list[tuple[int, int] | None] = []
    if isinstance(obj, dict):
        if obj.get("type") == "base64" and isinstance(obj.get("data"), str):
            out.append(png_dims(obj["data"]))
        for v in obj.values():
            out += _image_dims(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _image_dims(v)
    return out


def estimate_request_input_tokens(kwargs: dict[str, Any], image_tokens_each: int) -> int:
    """Text ≈ chars/3.5; each image ≈ w·h/750 from its PNG header (fallback `image_tokens_each`)."""
    from eval.common import image_tokens

    req = {k: v for k, v in kwargs.items() if k in ("system", "messages", "output_config")}
    stripped, _ = strip_images(req)
    img = sum(image_tokens(*d) if d else image_tokens_each for d in _image_dims(req))
    return text_tokens(canonical_json(stripped)) + img


def _first_text(content: list[Any]) -> str | None:
    for b in content or []:
        t = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        if t == "text":
            return b.get("text") if isinstance(b, dict) else b.text
    return None


def make_client() -> Any:
    """Real SDK client (reads ANTHROPIC_API_KEY / .env via settings; the key is never printed)."""
    import anthropic

    from backend.app.settings import get_settings

    key = get_settings().anthropic_api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


class StructuredCaller:
    """One model + one cache namespace. Thread-safe enough for a small worker pool."""

    def __init__(
        self,
        *,
        model: str,
        cache: ResponseCache,
        dry_run: bool,
        mock_fn: MockFn | None = None,
        tracker: SpendTracker | None = None,
        client: Any | None = None,
        max_tokens: int = 2000,
        effort: str = "default",
        image_tokens_each: int = 1400,
    ):
        self.model = model
        self.cache = cache
        self.dry_run = dry_run
        self.mock_fn = mock_fn
        self.tracker = tracker
        self.client = client
        self.max_tokens = max_tokens
        self.effort = effort
        self.image_tokens_each = image_tokens_each
        self._lock = threading.Lock()

    def build_kwargs(self, *, system: Any, content: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort != "default":
            output_config["effort"] = self.effort
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": content}],
            "output_config": output_config,
        }
        if system:
            kwargs["system"] = system
        return kwargs

    def key_for(self, kwargs: dict[str, Any]) -> str:
        return request_key(kwargs)

    def call(
        self, *, system: Any, content: list[dict[str, Any]], schema: dict[str, Any], mock_ctx: Any = None
    ) -> LLMResult:
        kwargs = self.build_kwargs(system=system, content=content, schema=schema)
        key = self.key_for(kwargs)
        hit = self.cache.get(key)
        if hit is not None:
            return LLMResult(
                key=key,
                parsed=hit.get("parsed"),
                text=hit.get("text"),
                stop_reason=hit.get("stop_reason"),
                usage=hit.get("usage") or {},
                model=hit.get("model", self.model),
                cached=True,
                mock=bool(hit.get("mock")),
                error=hit.get("error"),
                latency_ms=hit.get("latency_ms"),
            )
        if self.dry_run:
            return self._mock(key, kwargs, mock_ctx)
        return self._live(key, kwargs)

    # ------------------------------------------------------------------ mock
    def _mock(self, key: str, kwargs: dict[str, Any], ctx: Any) -> LLMResult:
        if self.mock_fn is None:
            raise RuntimeError("dry run without a mock function")
        stripped, _ = strip_images(kwargs)
        parsed = self.mock_fn(stripped, ctx)
        text = json.dumps(parsed)
        usage = {
            "input_tokens": estimate_request_input_tokens(kwargs, self.image_tokens_each),
            "output_tokens": text_tokens(text),
        }
        res = LLMResult(
            key=key, parsed=parsed, text=text, stop_reason="end_turn", usage=usage, model=self.model, mock=True
        )
        self.cache.put(key, {**res.__dict__, "cached": False})
        return res

    # ------------------------------------------------------------------ live
    def _live(self, key: str, kwargs: dict[str, Any]) -> LLMResult:
        import anthropic

        if self.client is None:
            self.client = make_client()
        if self.tracker:
            with self._lock:
                self.tracker.check()
        t0 = time.perf_counter()
        try:
            resp = self.client.messages.create(**kwargs)
        except (
            anthropic.BadRequestError,
            anthropic.NotFoundError,
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
        ) as e:
            # Non-retryable: record but do not cache (a fixed request would be retried on resume).
            return LLMResult(
                key=key,
                parsed=None,
                text=None,
                stop_reason=None,
                usage={},
                model=self.model,
                error=f"{type(e).__name__}: {getattr(e, 'message', str(e))}",
            )
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            return LLMResult(
                key=key,
                parsed=None,
                text=None,
                stop_reason=None,
                usage={},
                model=self.model,
                error=f"{type(e).__name__}: transient, not cached",
            )
        latency = (time.perf_counter() - t0) * 1000
        usage = resp.usage.model_dump() if resp.usage else {}
        if self.tracker:
            with self._lock:
                self.tracker.add(self.model, usage)
        text = _first_text(resp.content)
        parsed, err = None, None
        if resp.stop_reason == "refusal":
            err = "refusal"
        elif resp.stop_reason == "max_tokens":
            err = "max_tokens"
        elif text is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as e:
                err = f"json: {e}"
        else:
            err = "no text block"
        res = LLMResult(
            key=key,
            parsed=parsed,
            text=text,
            stop_reason=resp.stop_reason,
            usage=usage,
            model=resp.model or self.model,
            error=err,
            latency_ms=latency,
        )
        self.cache.put(key, {**res.__dict__, "cached": False, "response_id": resp.id})
        return res


# ------------------------------------------------------------------------------------------------ tutor injection
@dataclass
class CallLog:
    key: str
    model: str
    text: str | None
    stop_reason: str | None
    usage: dict[str, Any]
    cached: bool
    mock: bool
    request: dict[str, Any] = field(default_factory=dict)  # images stripped


class CachingAnthropic:
    """Duck-typed `anthropic.Anthropic` for injection into backend.app.tutor.service.generate_debrief(client=...).

    Implements `.messages.create(**kwargs)` (and `.messages.parse` → create) returning real SDK `Message`
    objects. Every request is cached (resumable), costed, and appended to `self.calls` so the eval can score the
    first try and the regeneration separately. In dry-run, `mock_fn(request_without_images, ctx)` returns the
    JSON body.
    """

    def __init__(
        self,
        *,
        cache: ResponseCache,
        dry_run: bool,
        mock_fn: MockFn | None = None,
        tracker: SpendTracker | None = None,
        real_client: Any | None = None,
        image_tokens_each: int = 1400,
    ):
        self.cache = cache
        self.dry_run = dry_run
        self.mock_fn = mock_fn
        self.tracker = tracker
        self.real_client = real_client
        self.image_tokens_each = image_tokens_each
        self.calls: list[CallLog] = []
        self.ctx: Any = None
        self.messages = _Messages(self)

    def reset(self, ctx: Any = None) -> None:
        self.calls = []
        self.ctx = ctx


class _Messages:
    def __init__(self, outer: CachingAnthropic):
        self.o = outer

    def parse(self, **kwargs: Any) -> Any:
        return self.create(**kwargs)

    def create(self, **kwargs: Any) -> Any:
        from anthropic.types import Message

        o = self.o
        key = request_key(kwargs)
        stripped, _ = strip_images(kwargs)
        hit = o.cache.get(key)
        if hit is not None:
            msg = Message.model_validate(hit["message"])
            o.calls.append(
                CallLog(
                    key,
                    msg.model,
                    _first_text(msg.content),
                    msg.stop_reason,
                    msg.usage.model_dump() if msg.usage else {},
                    True,
                    bool(hit.get("mock")),
                    stripped,
                )
            )
            return msg
        if o.dry_run:
            if o.mock_fn is None:
                raise RuntimeError("dry run without a mock function")
            body = o.mock_fn(stripped, o.ctx)
            text = json.dumps(body)
            msg = Message.model_validate(
                {
                    "id": "msg_mock_" + key[:16],
                    "type": "message",
                    "role": "assistant",
                    "model": kwargs["model"],
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": estimate_request_input_tokens(kwargs, o.image_tokens_each),
                        "output_tokens": text_tokens(text),
                    },
                }
            )
            o.cache.put(key, {"message": msg.to_dict(), "mock": True})
            o.calls.append(CallLog(key, msg.model, text, "end_turn", msg.usage.model_dump(), False, True, stripped))
            return msg
        if o.real_client is None:
            o.real_client = make_client()
        if o.tracker:
            o.tracker.check()
        msg = o.real_client.messages.create(**kwargs)  # errors propagate: the tutor service handles fallback
        usage = msg.usage.model_dump() if msg.usage else {}
        if o.tracker:
            o.tracker.add(kwargs["model"], usage)
        o.cache.put(key, {"message": msg.to_dict(), "mock": False})
        o.calls.append(
            CallLog(key, msg.model, _first_text(msg.content), msg.stop_reason, usage, False, False, stripped)
        )
        return msg
