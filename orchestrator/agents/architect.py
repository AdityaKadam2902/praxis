"""
agents/architect.py

Architect agent — second stage. Takes the PM's TaskSpec plus a snapshot
of the relevant repo context and produces a design decision: which
file(s) to touch and the approach to take.

Scope-discipline instruction added after a consistent, repeated pattern
across nearly every run this session: for a request that only ever said
"add exponentiation support," Architect repeatedly decided that meant
inventing a tokenizer/parser module, an evaluator, operator precedence
tables, and a UI layer — none of which were asked for and none of which
exist in the seed repo. This wasn't a rare misfire; it was the default.
It also wasn't harmless: the runs with the worst retry storms (multiple
429s, empty-content loops, temperature bumps) were exactly the ones
where Architect's decision was this large, since a bigger decision means
a bigger Engineer response, which means more token/rate-limit pressure.
Fixing the root scope discipline is expected to reduce how often the
downstream resilience logic even needs to fire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from providers.base import Provider
from providers.factory import get_provider
from agents.pm import TaskSpec

SYSTEM_PROMPT = """You are a software architect. Given a scoped task and \
the current contents of the relevant repo files, decide which file(s) \
need to change and describe the approach in 2-4 sentences.

SCOPE DISCIPLINE — this is a hard constraint, not a suggestion: decide \
the SMALLEST change that satisfies the literal task description. Do \
NOT invent new modules, parsers, tokenizers, evaluators, UI layers, or \
any other functionality that was not explicitly asked for, even if you \
can imagine how it might eventually be useful. Only propose a new file \
if the task cannot be accomplished by modifying an existing one.

Concrete example of what NOT to do: if the task says "add exponentiation \
support to the calculator," the correct scope is "add one power(a, b) \
function to the existing calculator file." It is NOT correct to also \
design a new expression parser, operator precedence table, tokenizer, \
or UI button — none of that was requested, and the repo context will \
show you whether such things even exist yet. If they don't exist, that \
is a signal they're out of scope, not an invitation to create them.

Be specific about function/class names that should be added or \
modified. Do not write code — that's the Engineer's job. Output ONLY \
the design decision text, nothing else."""

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
        repo_context so a hallucinated filename doesn't get treated as a
        real target. dict.fromkeys dedupes while preserving order — a
        filename mentioned twice in the decision text shouldn't appear
        twice in this list (observed in a real run).
        """
        candidates = _PY_FILE_RE.findall(decision_text)
        known_files = set(_PY_FILE_RE.findall(repo_context))
        matched = list(dict.fromkeys(f for f in candidates if f in known_files))
        return matched if matched else sorted(known_files)