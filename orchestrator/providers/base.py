"""
providers/base.py

One interface, three backends (Ollama / Groq / Gemini), all free. Swapping
providers should never touch agents/engineer.py or the calibration code —
they only know about `Provider.generate(...)`. This is what makes the
model layer a config choice instead of an architectural one.

Every provider also reports `network_call: bool` so behavioral.py's time
signal can (eventually) discount network-bound latency separately from
actual generation time — see the note in providers/README below.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GenerationResponse:
    text: str
    model_used: str
    network_call: bool  # False for Ollama (local), True for Groq/Gemini


class Provider(ABC):
    """Every backend implements exactly this."""

    @abstractmethod
    def generate(self, model: str, system: str, prompt: str) -> GenerationResponse:
        ...

    @abstractmethod
    def fast_model_name(self) -> str:
        """The model to use for simple/medium difficulty tasks."""
        ...

    @abstractmethod
    def heavy_model_name(self) -> str:
        """The model to use for hard/complex tasks."""
        ...
