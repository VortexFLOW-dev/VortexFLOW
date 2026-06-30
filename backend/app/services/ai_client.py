# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""LLM client for the AI assistant (VRL/AI plan B2).

One small dispatch layer over two official SDKs:

- ``anthropic``  → Claude (the default, hosted).
- ``openai``     → OpenAI **and** any OpenAI-compatible endpoint (Ollama, vLLM,
                   LiteLLM, …) via a ``base_url`` override — the self-hosted /
                   no-egress path.

Both async clients are used so a call never blocks the event loop. Config comes
from :mod:`app.services.ai_config` (the decrypted key via ``get_api_key``).

**Security — this is the first code that makes an outbound request to an
admin-supplied ``base_url``** (the SSRF surface flagged in B1's review). Two
defenses live here:

1. A bounded request timeout and ``max_retries=0`` so a slow/hostile URL can't
   hang a worker or amplify timing.
2. Error messages are **sanitized** — :func:`_sanitize` maps the SDK exception to
   a short, fixed string keyed on type/HTTP-status only. The raw upstream
   response body is **never** surfaced, so the endpoint can't be used as an SSRF
   oracle that reflects an internal service's response back to the caller.

We deliberately do *not* block private/loopback IPs: pointing at an internal
Ollama is the whole point of the self-hosted path. VortexFlow is self-hosted-only
(the admin is the operator), so the residual SSRF risk is an admin scanning their
own network — bounded, not eliminated. Hosted-mode egress policy is a future hook.
"""

import time
from dataclasses import dataclass

from app.services import ai_config


class AiNotConfigured(Exception):
    """AI is unconfigured for the requested provider (e.g. missing key)."""


class AiError(Exception):
    """An upstream call failed. The message is already sanitized for display."""


def _sanitize(exc: Exception) -> str:
    """Map an SDK exception to a short, safe message.

    Never includes the raw upstream response body (SSRF-oracle defense). HTTP
    status codes and exception class are safe to surface; ``str(exc)`` is not.
    """
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in (401, 403):
            return "authentication failed — check the API key"
        if status == 404:
            return "model or endpoint not found"
        if status == 429:
            return "rate limited by the provider"
        return f"the endpoint returned HTTP {status}"
    if "Timeout" in name:
        return "the request timed out"
    if "Connection" in name:
        return "could not connect to the endpoint"
    return "the request failed"


def _resolve(raw: dict, secret_key: str) -> tuple[str, str | None, str | None, str]:
    provider = raw.get("provider", "anthropic")
    api_key = ai_config.get_api_key(raw, secret_key)
    base_url = (raw.get("base_url") or "").strip() or None
    model = (raw.get("model") or "").strip()
    return provider, api_key, base_url, model


async def complete(
    *,
    raw: dict,
    secret_key: str,
    user: str,
    system: str | None = None,
    max_tokens: int = 1024,
    timeout_s: float = 30.0,
) -> str:
    """Run a single completion against the configured provider. Returns the text.

    Raises :class:`AiNotConfigured` (config gap) or :class:`AiError` (sanitized
    upstream failure).
    """
    provider, api_key, base_url, model = _resolve(raw, secret_key)
    if not model:
        raise AiNotConfigured("no model configured")

    try:
        if provider == "anthropic":
            from anthropic import AsyncAnthropic

            if not api_key:
                raise AiNotConfigured("Anthropic API key not set")
            anthropic_client = AsyncAnthropic(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_s,
                max_retries=0,
            )
            # No thinking/sampling params — they 400 on claude-opus-4-8.
            kwargs: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": user}],
            }
            if system:
                kwargs["system"] = system
            resp = await anthropic_client.messages.create(**kwargs)
            return "".join(b.text for b in resp.content if b.type == "text")

        # openai + self_hosted both speak the OpenAI Chat Completions API.
        from openai import AsyncOpenAI

        # Self-hosted endpoints (Ollama/vLLM) often need no key, but the SDK
        # requires a non-empty string — a placeholder is harmless there.
        openai_client = AsyncOpenAI(
            api_key=api_key or "no-key-required",
            base_url=base_url,
            timeout=timeout_s,
            max_retries=0,
        )
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        oai_resp = await openai_client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,  # type: ignore[arg-type]
        )
        return oai_resp.choices[0].message.content or ""
    except (AiNotConfigured, AiError):
        raise
    except Exception as exc:  # noqa: BLE001 — sanitize everything before surfacing
        raise AiError(_sanitize(exc)) from exc


@dataclass
class TestResult:
    ok: bool
    provider: str
    model: str
    latency_ms: int | None
    sample: str | None
    error: str | None


async def test_connection(
    raw: dict, secret_key: str, timeout_s: float = 20.0
) -> TestResult:
    """Probe the configured provider with a tiny prompt. Never raises."""
    provider = raw.get("provider", "anthropic")
    model = (raw.get("model") or "").strip()
    start = time.monotonic()
    try:
        text = await complete(
            raw=raw,
            secret_key=secret_key,
            user="Reply with the single word: OK",
            max_tokens=16,
            timeout_s=timeout_s,
        )
        return TestResult(
            ok=True,
            provider=provider,
            model=model,
            latency_ms=int((time.monotonic() - start) * 1000),
            sample=(text or "").strip()[:80] or None,
            error=None,
        )
    except AiNotConfigured as exc:
        return TestResult(
            ok=False,
            provider=provider,
            model=model,
            latency_ms=None,
            sample=None,
            error=str(exc),
        )
    except AiError as exc:
        return TestResult(
            ok=False,
            provider=provider,
            model=model,
            latency_ms=int((time.monotonic() - start) * 1000),
            sample=None,
            error=str(exc),
        )
