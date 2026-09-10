"""
agents/engineer.py

Phase 2 update. Two changes from Phase 0:

1. Output shape: {filename: content} dict of complete files, not a
   single solution_code string — per build spec section 1's decision to
   use full-file replacement rather than diffs, avoiding patch-application
   as a failure surface.
2. Model selection: now calls orchestrator/routing.py's trust-based
   router (real Kuzu calibration history) instead of the hardcoded
   difficulty-only check. PRAXIS_FORCE_TIER still works as an explicit
   override, unchanged from Phase 0 — useful for deliberately testing
   tier behavior.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from calibration.verbalized import extract_verbalized_confidence, strip_confidence_line, CONFIDENCE_PROMPT_SUFFIX
from providers.base import Provider
from providers.factory import get_provider
from agents.pm import TaskSpec
from agents.architect import DesignDecision
from routing import select_model_for_task

SYSTEM_PROMPT = """You are a careful software engineer. You will be given \
a task, a design decision from the architect, and the current contents \
of relevant repo files. Implement the change.

Output format: for EACH file you create or modify, output a block \
exactly like this (repeat for multiple files):

FILE: <relative/path/to/file.py>
```
<the COMPLETE file contents, not just the changed part>
```

After all file blocks, on a new final line, output:
CONFIDENCE: <a number between 0 and 100>
"""

_FILE_BLOCK_RE = re.compile(
    r"FILE:\s*(?P<path>\S+)\s*\n```(?:\w+)?\n(?P<content>.*?)\n```",
    re.DOTALL,
)


@dataclass
class EngineerAttempt:
    """Phase 0's original shape — restored here because
    benchmark/run_benchmark.py still calls solve() and reads
    .solution_code directly. Phase 2's implement() below returns a
    different dataclass (ImplementationAttempt) rather than repurposing
    this one, so neither script silently breaks the other."""
    task_id: str
    model_used: str
    solution_code: str
    raw_response: str
    verbalized_confidence: float
    time_taken_seconds: float
    revision_count: int
    network_call: bool


@dataclass
class ImplementationAttempt:
    task_id: str
    model_used: str
    changed_files: dict[str, str]
    raw_response: str
    verbalized_confidence: float
    time_taken_seconds: float
    revision_count: int
    network_call: bool


# Phase 0's original system prompt + confidence-only output format —
# unchanged, still used by solve().
_SOLVE_SYSTEM_PROMPT = """You are a careful software engineer. You will be given
a function signature and a description. Write a complete, correct Python
implementation. Output ONLY the code (no markdown fences, no explanation),
followed by the confidence line described below."""

# Phase 0's original task-type -> baseline expected solve time, used by
# behavioral.py's time signal. Restored here because
# benchmark/run_benchmark.py imports this directly — dropped by mistake
# when solve()/EngineerAttempt were restored above; this was the other
# thing Phase 0's engineer.py exported that Phase 2's rewrite didn't
# carry forward.
BASELINE_TIME_SECONDS = {
    "simple": 15.0,
    "medium": 30.0,
    "hard": 60.0,
}


class EngineerAgent:
    def __init__(self, provider: Provider | None = None) -> None:
        self.provider = provider or get_provider()
        forced = os.environ.get("PRAXIS_FORCE_TIER", "")
        print(
            f"[engineer] PRAXIS_FORCE_TIER resolved to: '{forced}' "
            "(empty means trust-based routing is active, not forced)"
        )

    def _select_model(self, task_type: str, difficulty: str) -> str:
        forced = os.environ.get("PRAXIS_FORCE_TIER", "").lower()
        if forced == "fast":
            return self.provider.fast_model_name()
        if forced == "heavy":
            return self.provider.heavy_model_name()
        return select_model_for_task(self.provider, task_type, difficulty)

    def solve(
        self,
        task_id: str,
        prompt: str,
        difficulty: str = "medium",
        max_revisions: int = 2,
    ) -> EngineerAttempt:
        """
        Phase 0's original single-function interface, restored verbatim
        (aside from now sharing _select_model's routing logic, which
        needs a task_type — Phase 0's seed_tasks.json tasks don't have
        one in this call path, so this passes "unknown", which
        routing.py's cold-start fallback handles the same as any other
        task_type with no history: falls back to the difficulty-only
        default, identical to Phase 0's original behavior).
        """
        model = self._select_model(task_type="unknown", difficulty=difficulty)
        full_prompt = f"{prompt}\n\n{CONFIDENCE_PROMPT_SUFFIX}"

        start = time.monotonic()
        response = self.provider.generate(model=model, system=_SOLVE_SYSTEM_PROMPT, prompt=full_prompt)
        raw_response = response.text
        revision_count = 0

        conf = extract_verbalized_confidence(raw_response)
        while conf.normalized < 0.5 and revision_count < max_revisions:
            revision_prompt = (
                f"{full_prompt}\n\nYour previous attempt:\n{raw_response}\n\n"
                "You reported low confidence. Reconsider and improve it."
            )
            response = self.provider.generate(model=model, system=_SOLVE_SYSTEM_PROMPT, prompt=revision_prompt)
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

    def implement(
        self,
        task: TaskSpec,
        design: DesignDecision,
        repo_context: str,
        max_revisions: int = 2,
    ) -> ImplementationAttempt:
        model = self._select_model(task.task_type, task.difficulty)
        prompt = (
            f"Task: {task.scoped_description}\n\n"
            f"Architect's decision: {design.decision_text}\n\n"
            f"Current relevant repo files:\n{repo_context}\n\n"
            f"{CONFIDENCE_PROMPT_SUFFIX}"
        )

        start = time.monotonic()
        response = self.provider.generate(model=model, system=SYSTEM_PROMPT, prompt=prompt)
        raw_response = response.text
        revision_count = 0

        conf = extract_verbalized_confidence(raw_response)
        changed_files = self._parse_files(raw_response)

        # Revise if confidence is low OR if the model failed to produce any
        # valid FILE blocks at all — the second condition matters because a
        # response with high stated confidence but zero parseable files is
        # useless to the pipeline regardless of what CONFIDENCE says.
        while (conf.normalized < 0.5 or not changed_files) and revision_count < max_revisions:
            revision_prompt = (
                f"{prompt}\n\nYour previous attempt:\n{raw_response}\n\n"
                "You reported low confidence, or produced no valid FILE blocks "
                "in the required format. Reconsider and improve it."
            )
            response = self.provider.generate(model=model, system=SYSTEM_PROMPT, prompt=revision_prompt)
            raw_response = response.text
            conf = extract_verbalized_confidence(raw_response)
            changed_files = self._parse_files(raw_response)
            revision_count += 1

        elapsed = time.monotonic() - start

        return ImplementationAttempt(
            task_id=task.task_id,
            model_used=model,
            changed_files=changed_files,
            raw_response=raw_response,
            verbalized_confidence=conf.normalized,
            time_taken_seconds=elapsed,
            revision_count=revision_count,
            network_call=response.network_call,
        )

    def _parse_files(self, raw_text: str) -> dict[str, str]:
        """
        Extract {path: content} blocks. Returns an empty dict if none are
        found — implement()'s revision loop treats that the same as low
        verbalized confidence: a signal to try again, not a crash.
        """
        files: dict[str, str] = {}
        for match in _FILE_BLOCK_RE.finditer(raw_text):
            path = match.group("path").strip()
            content = match.group("content")
            files[path] = content
        return files