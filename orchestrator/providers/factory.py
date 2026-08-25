"""
providers/factory.py

The one place that decides which backend is active. Switch providers by
changing PRAXIS_PROVIDER (env var) — nothing else in the codebase needs to
change. Defaults to Ollama since it's the only option guaranteed to work
with zero setup (no API key, no internet dependency).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from providers.base import Provider
from providers.ollama_provider import OllamaProvider
from providers.groq_provider import GroqProvider
from providers.gemini_provider import GeminiProvider

# Loads .env into os.environ if present. Safe to call even with no .env
# file (e.g. in CI, or if you're exporting vars manually) — it's a no-op
# in that case. This is the ONLY place dotenv gets loaded, so every
# provider downstream can keep using plain os.environ.get() without
# needing to know or care whether the value came from a .env file or a
# real shell export.
load_dotenv()


def get_provider() -> Provider:
    choice = os.environ.get("PRAXIS_PROVIDER", "ollama").lower()

    if choice == "ollama":
        return OllamaProvider()
    if choice == "groq":
        return GroqProvider()
    if choice == "gemini":
        return GeminiProvider()

    raise ValueError(
        f"Unknown PRAXIS_PROVIDER '{choice}'. Expected one of: ollama, groq, gemini."
    )
