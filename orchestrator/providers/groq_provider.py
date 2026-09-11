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
                response = self.client.post(
                    "/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        # Real incident: openai/gpt-oss-20b is a reasoning
                        # model that spends tokens on an internal
                        # "reasoning" field before producing "content" —
                        # with no max_tokens set (Groq's default applied),
                        # a verbose reasoning trace exhausted the entire
                        # budget and returned finish_reason="length" with
                        # completely empty content. Setting this
                        # generously gives room for both.
                        "max_tokens": 4096,
                    },
                )

                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                    # Honor Groq's Retry-After header if present, otherwise
                    # exponential backoff (2s, 4s, 8s, 16s).
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

                if not text or not text.strip():
                    # Real incident: Groq returned HTTP 200 with a
                    # genuinely empty content string, which crashed
                    # reviewer.py's parsing silently (no error, just
                    # nothing to parse). Surface finish_reason and the
                    # raw choice so this is diagnosable instead of a
                    # repeat of the "silent 0/0" pattern this project
                    # has hit more than once already.
                    print(
                        f"[groq] WARNING: empty content in response. "
                        f"finish_reason={choice.get('finish_reason')!r} "
                        f"full_choice={choice!r}"
                    )

                return GenerationResponse(text=text, model_used=model, network_call=True)

            except httpx.HTTPStatusError as exc:
                last_exception = exc
                if exc.response.status_code not in _RETRYABLE_STATUS_CODES or attempt >= _MAX_RETRIES:
                    raise
                # Retryable but raise_for_status already threw — shouldn't
                # normally reach here given the check above, but handles
                # the case defensively rather than assuming the ordering
                # always holds.
                delay = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(delay)

        # Exhausted all retries — raise the last real error rather than a
        # generic one, so the caller sees exactly what Groq returned.
        if last_exception:
            raise last_exception
        raise RuntimeError("Groq request failed after retries with no captured exception.")