"""
providers/ollama_provider.py

Local, offline, zero network dependency. Kept as the default/fallback
provider — the one that works even with no internet, which matters for a
project whose whole premise is "no cost, runs on your machine."
"""

from __future__ import annotations

import httpx

from providers.base import Provider, GenerationResponse


class OllamaProvider(Provider):
    def __init__(
        self,
        host: str = "http://localhost:11434",
        fast_model: str = "qwen2.5:7b",
        heavy_model: str = "qwen2.5:14b",
    ) -> None:
        self.client = httpx.Client(base_url=host, timeout=120.0)
        self._fast_model = fast_model
        self._heavy_model = heavy_model

    def fast_model_name(self) -> str:
        return self._fast_model

    def heavy_model_name(self) -> str:
        return self._heavy_model

    def generate(self, model: str, system: str, prompt: str) -> GenerationResponse:
        response = self.client.post(
            "/api/generate",
            json={"model": model, "prompt": prompt, "system": system, "stream": False},
        )
        response.raise_for_status()
        return GenerationResponse(
            text=response.json()["response"],
            model_used=model,
            network_call=False,
        )
