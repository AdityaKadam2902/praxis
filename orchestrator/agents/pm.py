"""
agents/pm.py

PM agent — first stage of the Phase 2 pipeline. Takes a raw feature
request and produces a TaskSpec: task_type, difficulty, a scoped
description, and a PR description.

task_type/difficulty exist specifically because the Phase 2 build spec
(section 4/6) identified that the trust-based router needs them to
bucket calibration history, and Kuzu's Task node already has fields for
both — this closes that gap rather than leaving PM's output too vague
to route on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from providers.base import Provider
from providers.factory import get_provider

SYSTEM_PROMPT = """You are a product manager for a small software team. \
Given a feature request, produce exactly four fields, each on its own \
line, in this exact format (no markdown, no extra commentary, no blank \
lines between fields):

TASK_TYPE: <one of: feature_add, bug_fix, refactor>
DIFFICULTY: <one of: simple, medium, hard>
SCOPED_DESCRIPTION: <1-3 sentences precisely scoping what should change>
PR_DESCRIPTION: <1-2 sentences suitable as a pull request description>
"""

_FIELD_RE = re.compile(
    r"TASK_TYPE:\s*(?P<task_type>\S+)\s*\n"
    r"DIFFICULTY:\s*(?P<difficulty>\S+)\s*\n"
    r"SCOPED_DESCRIPTION:\s*(?P<scoped>.+?)\s*\n"
    r"PR_DESCRIPTION:\s*(?P<pr>.+)",
    re.DOTALL,
)

_VALID_TASK_TYPES = {"feature_add", "bug_fix", "refactor"}
_VALID_DIFFICULTIES = {"simple", "medium", "hard"}


@dataclass
class TaskSpec:
    task_id: str
    task_type: str
    difficulty: str
    scoped_description: str
    pr_description: str


class PMAgent:
    def __init__(self, provider: Provider | None = None) -> None:
        self.provider = provider or get_provider()

    def scope(self, task_id: str, feature_request: str) -> TaskSpec:
        response = self.provider.generate(
            model=self.provider.fast_model_name(),
            system=SYSTEM_PROMPT,
            prompt=feature_request,
        )
        return self._parse(task_id, feature_request, response.text)

    def _parse(self, task_id: str, feature_request: str, raw_text: str) -> TaskSpec:
        """
        Separated from scope() specifically so the parsing logic is
        testable without a live LLM call — same reasoning as
        calibration/verbalized.py splitting extraction from generation.
        """
        match = _FIELD_RE.search(raw_text)

        if match:
            task_type = match.group("task_type").strip().lower()
            difficulty = match.group("difficulty").strip().lower()
            # Fail closed on out-of-vocabulary values too, not just on a
            # totally failed regex match — a model that writes
            # "TASK_TYPE: enhancement" instead of "feature_add" shouldn't
            # silently poison the router's bucketing with an unrecognized
            # category.
            if task_type not in _VALID_TASK_TYPES:
                task_type = "feature_add"
            if difficulty not in _VALID_DIFFICULTIES:
                difficulty = "medium"
            return TaskSpec(
                task_id=task_id,
                task_type=task_type,
                difficulty=difficulty,
                scoped_description=match.group("scoped").strip(),
                pr_description=match.group("pr").strip(),
            )

        # Fail closed entirely: if the model didn't follow the format at
        # all, don't crash the pipeline — fall back to safe defaults,
        # same "fail closed to neutral" precedent Phase 0's
        # verbalized.py established rather than assuming a favorable parse.
        return TaskSpec(
            task_id=task_id,
            task_type="feature_add",
            difficulty="medium",
            scoped_description=feature_request.strip(),
            pr_description=feature_request.strip()[:100],
        )