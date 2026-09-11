"""
agents/reviewer.py

Reviewer agent — fifth stage. Reads the real diff (via
git_ops.diff_against) and QA's real test result, and decides whether to
approve or request changes.

Key design choice: if QA didn't pass, this agent auto-rejects WITHOUT
even calling the model — a structural guarantee that failing tests can
never be approved, rather than trusting a system prompt instruction to
always be honored. Same principle as qa.py and calibration/outcome.py:
keep ground-truth decisions out of the model's hands wherever a hard
rule can enforce them directly instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from providers.base import Provider
from providers.factory import get_provider
import git_ops

SYSTEM_PROMPT = """You are a code reviewer. You will be given a diff and \
the result of running the test suite (which already passed — you are only \
called when it did). Review the diff itself for obvious problems: unused \
imports, missing input validation compared to the rest of the file, \
overly broad exception handling, or anything that contradicts the stated \
task. Output exactly two fields, each on its own line:

VERDICT: <approve or request_changes>
COMMENTS: <1-3 sentences explaining your verdict>
"""

_VERDICT_RE = re.compile(
    r"VERDICT:\s*(?P<verdict>\S+)\s*\n"
    r"COMMENTS:\s*(?P<comments>.+)",
    re.DOTALL,
)

_VALID_VERDICTS = {"approve", "request_changes"}


@dataclass
class ReviewResult:
    task_id: str
    verdict: str  # "approve" | "request_changes"
    comments: str


class ReviewerAgent:
    def __init__(self, provider: Provider | None = None) -> None:
        self.provider = provider or get_provider()

    def review(
        self,
        task_id: str,
        repo_dir: str,
        qa_passed: bool,
        qa_summary: str,
        base_ref: str = "main",
    ) -> ReviewResult:
        if not qa_passed:
            return ReviewResult(
                task_id=task_id,
                verdict="request_changes",
                comments=f"Auto-rejected: QA did not pass ({qa_summary}). "
                         f"Never sent to the model for review.",
            )

        diff = git_ops.diff_against(repo_dir, base_ref=base_ref)
        if not diff.strip():
            return ReviewResult(
                task_id=task_id,
                verdict="request_changes",
                comments="Auto-rejected: diff is empty, nothing to review.",
            )

        prompt = f"Test result: {qa_summary}\n\nDiff:\n{diff}"
        response = self.provider.generate(
            model=self.provider.fast_model_name(),
            system=SYSTEM_PROMPT,
            prompt=prompt,
        )
        return self._parse(task_id, response.text)

    def _parse(self, task_id: str, raw_text: str) -> ReviewResult:
        """Separated from review() for testability without a live LLM call,
        same pattern used throughout the agent files."""
        match = _VERDICT_RE.search(raw_text)
        if not match:
            # Same lesson as every other silent-failure incident in this
            # project (QA's charmap error, the missing-pytest incident,
            # the pytest_output.py regex bug): never fail closed without
            # showing the actual raw text that caused it. Truncated to
            # keep it readable in the pipeline's console output.
            print(f"[reviewer] [diagnostic] response did not match expected format:")
            print(f"    {raw_text.strip()[:800]!r}")
            return ReviewResult(
                task_id=task_id,
                verdict="request_changes",
                comments="Auto-rejected: reviewer response could not be parsed.",
            )
        verdict = match.group("verdict").strip().lower()
        if verdict not in _VALID_VERDICTS:
            verdict = "request_changes"  # fail closed on out-of-vocabulary too
        return ReviewResult(
            task_id=task_id,
            verdict=verdict,
            comments=match.group("comments").strip(),
        )