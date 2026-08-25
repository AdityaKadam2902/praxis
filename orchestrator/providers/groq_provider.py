"""
providers/groq_provider.py

Groq's free tier, OpenAI-compatible endpoint. Fast (LPU inference), good
free rate limits. Requires GROQ_API_KEY env var — get one free at
https://console.groq.com/keys

Groq's available models change often enough that hardcoding a name in
code is fragile (this bit us once already — llama-3.1-8b-instant /
llama-3.3-70b-versatile returned 404 despite being documented, likely
mid-deprecation). Model names are now overridable via .env
(GROQ_FAST_MODEL / GROQ_HEAVY_MODEL) so a future Groq lineup change is a
one-line .env edit, not a code change. Current full list:
https://console.groq.com/docs/models
"""

from __future__ import annotations

import os

import httpx

from providers.base import Provider, GenerationResponse

# openai/gpt-oss-20b and openai/gpt-oss-120b, as of Aug 2026 — verified
# current and stable across multiple independent sources at time of
# writing. Override via .env if Groq's lineup changes again.
DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_HEAVY_MODEL = "openai/gpt-oss-120b"


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
                "and export GROQ_API_KEY=... before using GroqProvider."
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
        response = self.client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
        )
        if response.status_code == 404:
            raise RuntimeError(
                f"Groq returned 404 for model '{model}'. This usually means the "
                f"model has been renamed or deprecated. Check the current list at "
                f"https://console.groq.com/docs/models and set GROQ_FAST_MODEL / "
                f"GROQ_HEAVY_MODEL in .env to a model from that list."
            )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return GenerationResponse(text=text, model_used=model, network_call=True)