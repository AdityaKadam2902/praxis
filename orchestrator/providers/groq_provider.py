"""
providers/groq_provider.py

Groq's free tier, OpenAI-compatible endpoint. Requires GROQ_API_KEY env
var (and optionally GROQ_FAST_MODEL/GROQ_HEAVY_MODEL to override the
defaults if Groq deprecates them — check
https://console.groq.com/docs/models for current names).

Retry-with-backoff added after a real incident: repeated Phase 2 test
runs in quick succession hit Groq's free-tier rate limit (429 Too Many
Requests), which crashed the whole pipeline with an unhandled
HTTPStatusError. With 6 agents potentially calling the model per task
(plus Engineer's own revision loop), transient rate limits are an
expected condition under normal use, not an edge case — retrying with
backoff belongs here, once, rather than duplicated in every agent file
that calls generate().
"""

from __future__ import annotations

import os
import time

import httpx

from providers.base import Provider, GenerationResponse

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_HEAVY_MODEL = "openai/gpt-oss-120b"

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 4
_BASE_BACKOFF_SECONDS = 2.0


class GroqProvider(Provider):
    def __init__(
        self,
        api_key: str | None = None,
        fast_model: str | None = None,
        heavy_model: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY not set. Get a free key at https://console.groq.com/keys "
                "and add it to .env before using GroqProvider."
            )
        self.client = httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {key}"},
            timeout=60.0,
        )
        self._fast_model = fast_model or os.environ.get("GROQ_FAST_MODEL", DEFAULT_FAST_MODEL)
        self._heavy_model = heavy_model or os.environ.get("GROQ_HEAVY_MODEL", DEFAULT_HEAVY_MODEL)

    def fast_model_name(self) -> str:
        return self._fast_model

    def heavy_model_name(self) -> str:
        return self._heavy_model

    def generate(self, model: str, system: str, prompt: str) -> GenerationResponse:
        last_exception: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                # Nudge temperature up slightly on each retry. Real
                # incident: a reasoning model got stuck in a literal
                # repetition loop ("Ok.\nStop.\nOk.\nStop." repeated
                # hundreds of times) and hit finish_reason="length" with
                # empty content — no max_tokens value fixes a model that
                # never converges. Retrying at the exact same temperature
                # risks reproducing the same loop; a small bump gives the
                # retry a genuinely different sampling path to escape it.
                temperature = min(0.2 + attempt * 0.15, 0.8)

                response = self.client.post(
                    "/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": 4096,
                    },
                )

                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after else _BASE_BACKOFF_SECONDS * (2 ** attempt)
                    print(
                        f"[groq] {response.status_code} on attempt {attempt + 1}/{_MAX_RETRIES + 1} "
                        f"— retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                text = choice["message"]["content"]
                finish_reason = choice.get("finish_reason")

                if (not text or not text.strip()) and attempt < _MAX_RETRIES:
                    # Second real incident of this shape: this time a
                    # genuine repetition loop, not just an under-sized
                    # token budget. Retryable the same way a 429 is —
                    # PM/Architect/Reviewer/DevOps have no revision loop
                    # of their own (only Engineer does), so without this
                    # living here, any of them hitting this dead-ends the
                    # whole pipeline with no recovery path.
                    print(
                        f"[groq] Empty content on attempt {attempt + 1}/{_MAX_RETRIES + 1} "
                        f"(finish_reason={finish_reason!r}) — retrying at temperature={temperature + 0.15:.2f}"
                    )
                    continue

                if not text or not text.strip():
                    # Exhausted retries and still empty — surface full
                    # diagnostic detail rather than silently returning "".
                    print(
                        f"[groq] WARNING: empty content after {_MAX_RETRIES + 1} attempts. "
                        f"finish_reason={finish_reason!r} full_choice={choice!r}"
                    )

                return GenerationResponse(text=text, model_used=model, network_call=True)

            except httpx.HTTPStatusError as exc:
                last_exception = exc
                if exc.response.status_code not in _RETRYABLE_STATUS_CODES or attempt >= _MAX_RETRIES:
                    raise
                delay = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(delay)

            except httpx.TransportError as exc:
                # Real incident: httpx.ConnectError ("[WinError 10054] An
                # existing connection was forcibly closed by the remote
                # host") crashed the pipeline outright — this is a
                # network-level error, not an HTTP status error, so the
                # except clause above never caught it at all. httpx.TransportError
                # is the base class covering ConnectError, ReadTimeout,
                # WriteTimeout, PoolTimeout, RemoteProtocolError, etc. —
                # all genuinely transient conditions worth retrying, most
                # likely here a stale keep-alive connection on a
                # long-lived client reused across many requests. httpx
                # opens a fresh connection on the next attempt
                # automatically.
                last_exception = exc
                if attempt >= _MAX_RETRIES:
                    raise
                delay = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(
                    f"[groq] Network error on attempt {attempt + 1}/{_MAX_RETRIES + 1} "
                    f"({type(exc).__name__}: {exc}) — retrying in {delay:.1f}s"
                )
                time.sleep(delay)

        if last_exception:
            raise last_exception
        raise RuntimeError("Groq request failed after retries with no captured exception.")