"""
agents/engineer.py

Phase 0's single agent. Talks to whichever Provider is configured
(Ollama / Groq / Gemini — see providers/factory.py), tiers between the
fast and heavy model by task complexity, and returns everything the
calibration engine needs: the solution code, the verbalized confidence,
and the raw process data (time taken, revision count, full reasoning
trace) for the behavioral signal.

Kept deliberately single-purpose for Phase 0 — PM/Architect/QA/Reviewer/
DevOps come in Phase 2 once routing has real calibration data to route on.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from calibration.verbalized import extract_verbalized_confidence, strip_confidence_line, CONFIDENCE_PROMPT_SUFFIX
from providers.base import Provider
from providers.factory import get_provider

# Task-type -> baseline expected solve time, used by behavioral.py's time
# signal. Rough seed values for Phase 0 — Phase 1 should compute these
# empirically per task-type from logged attempts instead of hardcoding.
#
# NOTE: if you're on a network provider (Groq/Gemini), these baselines
# will include network latency, not just "thinking time" — the numbers
# below assume local Ollama. Bump them up if you switch providers, or
# the behavioral time signal will read as "struggling" when it's really
# just network round-trip.
BASELINE_TIME_SECONDS = {
    "simple": 15.0,
    "medium": 30.0,
    "hard": 60.0,
}

SYSTEM_PROMPT = """You are a careful software engineer. You will be given a
function signature and a description. Write a complete, correct Python
implementation. Output ONLY the code (no markdown fences, no explanation),
followed by the confidence line described below."""


@dataclass
class EngineerAttempt:
    task_id: str
    model_used: str
    solution_code: str
    raw_response: str
    verbalized_confidence: float  # 0.0-1.0
    time_taken_seconds: float
    revision_count: int
    network_call: bool  # True if a network provider was used — see baseline note above


class EngineerAgent:
    def __init__(self, provider: Provider | None = None) -> None:
        # Defaults to whatever PRAXIS_PROVIDER env var says (ollama by
        # default). Pass an explicit provider in to override, e.g. for
        # tests or for running two providers side by side.
        self.provider = provider or get_provider()

        # Print once, at construction, exactly what PRAXIS_FORCE_TIER
        # resolved to — added after PRAXIS_SANDBOX had the same "code is
        # right but the env var mysteriously isn't landing" issue earlier.
        # This turns "is the override actually active" into a one-line
        # answer in the run output instead of a guessing game.
        forced = os.environ.get("PRAXIS_FORCE_TIER", "")
        print(f"[engineer] PRAXIS_FORCE_TIER resolved to: '{forced}' (empty means difficulty-based routing is active, not forced)")

    def _select_model(self, difficulty: str) -> str:
        """
        Phase 0 routing is intentionally simple and static: hard tasks get
        the heavy model, everything else gets the fast one. Phase 2 replaces
        this with the trust-based router that uses real calibration history
        instead of a difficulty label alone.

        PRAXIS_FORCE_TIER (env var: fast | heavy | unset) overrides this
        entirely — added after the first two full Phase 0 runs came back
        with zero outcome/ground_truth divergence across all 13 tasks.
        Groq's heavy tier (a 70B-class model) was acing every task,
        including the ones designed to be adversarial, which meant there
        was nothing for outcome-grounding to actually catch. Forcing the
        fast tier tests against a smaller model — more likely to produce
        the real mistakes this thesis needs to see, and also the model
        class Praxis is actually meant to run on long-term (local
        qwen2.5:7b/14b, not a 70B cloud model).
        """
        forced = os.environ.get("PRAXIS_FORCE_TIER", "").lower()
        if forced == "fast":
            return self.provider.fast_model_name()
        if forced == "heavy":
            return self.provider.heavy_model_name()
        return self.provider.heavy_model_name() if difficulty == "hard" else self.provider.fast_model_name()

    def solve(
        self,
        task_id: str,
        prompt: str,
        difficulty: str = "medium",
        max_revisions: int = 2,
    ) -> EngineerAttempt:
        model = self._select_model(difficulty)
        full_prompt = f"{prompt}\n\n{CONFIDENCE_PROMPT_SUFFIX}"

        start = time.monotonic()
        response = self.provider.generate(model=model, system=SYSTEM_PROMPT, prompt=full_prompt)
        raw_response = response.text
        revision_count = 0

        # Simple self-revision loop: if the model's own confidence is low,
        # give it one more pass with its own output as context. This is
        # exactly the kind of process signal behavioral.py's revision_count
        # is meant to capture — low initial confidence -> more revisions ->
        # lower behavioral score, independent of what the final verbalized
        # number claims.
        conf = extract_verbalized_confidence(raw_response)
        while conf.normalized < 0.5 and revision_count < max_revisions:
            revision_prompt = (
                f"{full_prompt}\n\nYour previous attempt:\n{raw_response}\n\n"
                "You reported low confidence. Reconsider and improve it."
            )
            response = self.provider.generate(model=model, system=SYSTEM_PROMPT, prompt=revision_prompt)
            raw_response = response.text
            conf = extract_verbalized_confidence(raw_response)
            revision_count += 1

        elapsed = time.monotonic() - start
        solution_code = strip_confidence_line(raw_response)

        return EngineerAttempt(
            task_id=task_id,
            model_used=model,
            solution_code=solution_code,
            raw_response=raw_response,
            verbalized_confidence=conf.normalized,
            time_taken_seconds=elapsed,
            revision_count=revision_count,
            network_call=response.network_call,
        )