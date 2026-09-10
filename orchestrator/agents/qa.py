"""
agents/qa.py

QA agent — fourth stage of the Phase 2 pipeline. Runs the seed repo's
own test suite (via whichever repo executor PRAXIS_SANDBOX selects) on
Engineer's already-committed changes, and returns the real, grounded
result.

Deliberately has NO LLM call anywhere in this file — same reasoning as
Phase 0's calibration/outcome.py: this is the one stage in the pipeline
that must have no model in the loop, because that's what makes its
verdict trustworthy as ground truth rather than another flavor of
self-assessment. If this stage ever gains an LLM call (e.g. to interpret
ambiguous failures), that's a design decision worth flagging explicitly,
not something to add quietly.
"""

from __future__ import annotations

from dataclasses import dataclass

from sandbox.factory import get_repo_executor
from sandbox.result import ExecutionResult


@dataclass
class QAResult:
    task_id: str
    execution_result: ExecutionResult
    passed: bool


class QAAgent:
    def __init__(self) -> None:
        self.executor = get_repo_executor()

    def test(
        self,
        task_id: str,
        repo_dir: str,
        test_command: list[str] | None = None,
    ) -> QAResult:
        """
        repo_dir must already have Engineer's changes written and
        committed (pipeline.py handles that via git_ops before calling
        this) — QA only runs the existing test suite, it doesn't touch
        git at all.
        """
        result = self.executor.run(task_id=task_id, repo_dir=repo_dir, test_command=test_command)
        return QAResult(task_id=task_id, execution_result=result, passed=result.succeeded)