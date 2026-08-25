"""
providers/gemini_provider.py

Gemini's free tier via Google AI Studio. Requires GEMINI_API_KEY env var —
get one free at https://aistudio.google.com/apikey

Model names current as of Jan 2026 knowledge — check
https://ai.google.dev/gemini-api/docs/models before relying on these,
confirm current free-tier model names and rate limits.
"""

from __future__ import annotations

import os

import httpx

from providers.base import Provider, GenerationResponse

DEFAULT_FAST_MODEL = "gemini-2.0-flash"
DEFAULT_HEAVY_MODEL = "gemini-2.0-flash"  # same model both tiers on free tier;
# swap heavy_model to a Pro variant if/when your account has access to one
# without incurring cost — verify current free-tier eligibility first.


class GeminiProvider(Provider):
    def __init__(
        self,
        api_key: str | None = None,
        fast_model: str = DEFAULT_FAST_MODEL,
        heavy_model: str = DEFAULT_HEAVY_MODEL,
    ) -> None:
        self.key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Get a free key at "
                "https://aistudio.google.com/apikey and export GEMINI_API_KEY=... "
                "before using GeminiProvider."
            )
        self.client = httpx.Client(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout=60.0,
        )
        self._fast_model = fast_model
        self._heavy_model = heavy_model

    def fast_model_name(self) -> str:
        return self._fast_model

    def heavy_model_name(self) -> str:
        return self._heavy_model

    def generate(self, model: str, system: str, prompt: str) -> GenerationResponse:
        response = self.client.post(
            f"/models/{model}:generateContent",
            params={"key": self.key},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": prompt}]}],
            },
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return GenerationResponse(text=text, model_used=model, network_call=True)
