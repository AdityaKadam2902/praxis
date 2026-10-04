"""
agents/reviewer.py

Reviewer agent — fifth stage. Reads the real diff (via
git_ops.diff_against) and QA's real test result, and decides whether to
approve or request changes.

Two hard-won design properties:

1. If QA didn't pass, this agent auto-rejects WITHOUT even calling the
   model — a structural guarantee that failing tests can never be
   approved, rather than trusting a system prompt instruction to always
   be honored.

2. If QA DID pass, the model is explicitly told so and told to weigh
   that as real evidence — added after two real, back-to-back false
   rejections: once a flat-out hallucinated claim ("require_numbers is
   undefined" when it was correctly imported and used exactly like every
   other function in the file), once a hedged-but-still-wrong worry
   ("this may not be enforced" about a check that was already correct
   and already executing successfully). Both claims were of a kind QA's
   real execution would have caught if true — a genuine NameError or an
   unenforced check failing at runtime shows up as a QA failure, not a
   pass. Reviewer previously had no awareness that QA already ran the
   actual code successfully; it was reasoning about the diff in a
   vacuum, disconnected from evidence sitting right next to it in the
   pipeline. This doesn't make Reviewer's judgment perfect, but it
   directly targets the demonstrated failure pattern rather than
   open-endedly parsing and re-verifying arbitrary natural-language
   claims, which would be far more fragile to build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from providers.base import Provider
from providers.factory import get_provider
import git_ops

SYSTEM_PROMPT = """You are a code reviewer. You will be given a diff and \
the result of running the test suite — the test suite ALREADY EXECUTED \
THIS EXACT CODE and it passed. That is real, direct evidence: if the \
code had an undefined name, a missing import, a NameError, or a check \
that silently failed to run, the test suite would have caught it as a \
failure, not a pass. Do not claim the code will crash, raise an \
undefined-name error, or fail to execute — the test run already proves \
otherwise. Focus instead on what the test run can't tell you: code \
style, missing edge-case tests, redundant logic, design concerns, or \
whether the diff actually matches what the task asked for. Output \
exactly two fields, each on its own line:

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

        prompt = (
            f"Test result: {qa_summary} — ALL TESTS PASSED, this code ran "
            f"successfully for real.\n\nDiff:\n{diff}"
        )
        response = self.provider.generate(
            model=self.provider.fast_model_name(),
            system=SYSTEM_PROMPT,
            prompt=prompt,
        )
        return self._parse(task_id, response.text)

    def _parse(self, task_id: str, raw_text: str) -> ReviewResult:
        match = _VERDICT_RE.search(raw_text)
        if not match:
            print(f"[reviewer] [diagnostic] response did not match expected format:")
            print(f"    {raw_text.strip()[:800]!r}")
            return ReviewResult(
                task_id=task_id,
                verdict="request_changes",
                comments="Auto-rejected: reviewer response could not be parsed.",
            )
        verdict = match.group("verdict").strip().lower()
        if verdict not in _VALID_VERDICTS:
            verdict = "request_changes"
        return ReviewResult(
            task_id=task_id,
            verdict=verdict,
            comments=match.group("comments").strip(),
        )