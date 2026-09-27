"""
agents/engineer.py

Phase 0's single-function interface (solve()/EngineerAttempt) and Phase
2's multi-file interface (implement()/ImplementationAttempt) coexist here
deliberately — restored side by side after an earlier version dropped
solve() entirely and broke benchmark/run_benchmark.py, which still
depends on it.
"""

from __future__ import annotations

import os
import time
import re
from dataclasses import dataclass

from calibration.verbalized import extract_verbalized_confidence, strip_confidence_line, CONFIDENCE_PROMPT_SUFFIX
from providers.base import Provider
from providers.factory import get_provider
from routing import select_model_for_task
from test_coverage_check import find_untested_new_functions

# Phase 0's original task-type -> baseline expected solve time, used by
# behavioral.py's time signal.
BASELINE_TIME_SECONDS = {
    "simple": 15.0,
    "medium": 30.0,
    "hard": 60.0,
}


@dataclass
class EngineerAttempt:
    """Phase 0's original shape — restored because benchmark/run_benchmark.py
    calls solve() and reads .solution_code directly."""
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


_SOLVE_SYSTEM_PROMPT = """You are a careful software engineer. You will be given
a function signature and a description. Write a complete, correct Python
implementation. Output ONLY the code (no markdown fences, no explanation),
followed by the confidence line described below."""

SYSTEM_PROMPT = """You are a careful software engineer. You will be given \
a task, a design decision from the architect, and the current contents \
of relevant repo files. Implement the change.

MANDATORY: for any new public function or class you add, or any existing \
one whose behavior you change, you must add or update a corresponding \
test in the relevant test file — even if the architect's design decision \
did not explicitly mention updating tests. Do this every time, \
unconditionally. (Added after a real incident: a function calling \
builtins.sum() without importing builtins shipped with 8/8 tests passing, \
because no test ever exercised the new function at all — QA can only \
catch what a test actually calls.)

Output format: for EACH file you create or modify, output a block \
exactly like this (repeat for multiple files):

FILE: <relative/path/to/file.py>
```
<the COMPLETE file contents, not just the changed part>
```

After all file blocks, on a new final line, output:
CONFIDENCE: <a number between 0 and 100>
"""

_FILE_BLOCK_RE = re.compile(r"FILE:\s*(?P<path>\S+)\s*\n```(?:\w+)?\n(?P<content>.*?)\n```", re.DOTALL)


class EngineerAgent:
    def __init__(self, provider: Provider | None = None) -> None:
        self.provider = provider or get_provider()
        forced = os.environ.get("PRAXIS_FORCE_TIER", "")
        print(f"[engineer] PRAXIS_FORCE_TIER resolved to: '{forced}' (empty means trust-based routing is active, not forced)")

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

    def _parse_files(self, raw_text: str) -> dict[str, str]:
        files = {}
        for match in _FILE_BLOCK_RE.finditer(raw_text):
            files[match.group("path").strip()] = match.group("content")
        return files

    def implement(
        self,
        task,
        design,
        repo_context: str,
        repo_dir: str,
        max_revisions: int = 2,
    ) -> ImplementationAttempt:
        """
        repo_dir added specifically to run the structural test-coverage
        check (test_coverage_check.py) as part of the same revision loop
        that already retries on low confidence or zero parsed files —
        added after two real incidents where a new function shipped with
        zero test awareness of its existence (once hiding a real bug,
        once leaving a hallucinated Reviewer bug report unchallengeable).
        A prompt-only instruction to always write tests was tried first
        and did not hold against an Architect decision that explicitly
        said tests weren't needed; this is the structural backstop.
        """
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
        missing_coverage = find_untested_new_functions(repo_dir, changed_files) if changed_files else []

        while (conf.normalized < 0.5 or not changed_files or missing_coverage) and revision_count < max_revisions:
            if missing_coverage and changed_files:
                names = ", ".join(f"{path}::{name}" for path, name in missing_coverage)
                nudge = (
                    f"\n\nYou introduced new function(s)/class(es) with no test "
                    f"referencing them: {names}. Add a test for each of these now, "
                    f"even though this wasn't explicitly requested — this is required."
                )
            else:
                nudge = "\n\nYour previous attempt did not produce valid FILE blocks. Try again, following the format exactly."

            revision_prompt = f"{prompt}\n\nYour previous attempt:\n{raw_response}{nudge}"
            response = self.provider.generate(model=model, system=SYSTEM_PROMPT, prompt=revision_prompt)
            raw_response = response.text
            conf = extract_verbalized_confidence(raw_response)
            changed_files = self._parse_files(raw_response)
            missing_coverage = find_untested_new_functions(repo_dir, changed_files) if changed_files else []
            revision_count += 1

        elapsed = time.monotonic() - start

        if missing_coverage:
            names = ", ".join(f"{path}::{name}" for path, name in missing_coverage)
            print(f"[engineer] WARNING: still missing test coverage after {revision_count} revisions: {names}")

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