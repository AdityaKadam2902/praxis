"""
agents/architect.py

Architect agent — second stage. Takes the PM's TaskSpec plus a snapshot
of the relevant repo context and produces a design decision: which
file(s) to touch and the approach to take.

Output is plain text for Phase 2 — not written to Kuzu as a queryable
ADR yet. That's a deliberate scope decision (build spec section 5): an
architectural decision has no clean ground-truth signal the way
code-against-tests does, so extending calibration to it now would mean
inventing a fake outcome signal. Revisit once Phase 3's ADR graph exists
and a decision that later gets reverted becomes a real, gradable outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from providers.base import Provider
from providers.factory import get_provider
from agents.pm import TaskSpec

SYSTEM_PROMPT = """You are a software architect. Given a scoped task and \
the current contents of the relevant repo files, decide which file(s) \
need to change and describe the approach in 2-4 sentences. Be specific \
about function/class names that should be added or modified. Do not \
write code — that's the Engineer's job. Output ONLY the design decision \
text, nothing else."""

_PY_FILE_RE = re.compile(r"[\w./]+\.py")


@dataclass
class DesignDecision:
    task_id: str
    decision_text: str
    target_files: list[str]  # best-effort; Engineer confirms the real target(s)


class ArchitectAgent:
    def __init__(self, provider: Provider | None = None) -> None:
        self.provider = provider or get_provider()

    def decide(self, task: TaskSpec, repo_context: str) -> DesignDecision:
        prompt = (
            f"Task: {task.scoped_description}\n\n"
            f"Current relevant repo files:\n{repo_context}"
        )
        response = self.provider.generate(
            model=self.provider.fast_model_name(),
            system=SYSTEM_PROMPT,
            prompt=prompt,
        )
        decision_text = response.text.strip()
        target_files = self._guess_target_files(decision_text, repo_context)
        return DesignDecision(task_id=task.task_id, decision_text=decision_text, target_files=target_files)

    def _guess_target_files(self, decision_text: str, repo_context: str) -> list[str]:
        """
        Best-effort extraction of filenames mentioned in the decision
        text, cross-checked against filenames that actually appear in
        repo_context — so a hallucinated filename doesn't get treated as
        a real target. Engineer still receives the full decision_text
        regardless; this is a convenience list, not the source of truth,
        so a wrong guess here doesn't block the pipeline, just makes
        Engineer's job slightly less pre-scoped.
        """
        candidates = _PY_FILE_RE.findall(decision_text)
        known_files = set(_PY_FILE_RE.findall(repo_context))
        matched = [f for f in candidates if f in known_files]
        return matched if matched else sorted(known_files)