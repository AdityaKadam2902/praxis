"""
agents/devops.py

DevOps agent — sixth and final stage. Purely mechanical: merges an
already-approved, already-tested branch via git_ops.merge_branch(). No
LLM call at all — same reasoning as qa.py: merging a reviewed branch is
a deterministic git operation with nothing for a model's judgment to add.
"""

from __future__ import annotations

from dataclasses import dataclass

import git_ops


@dataclass
class DevOpsResult:
    task_id: str
    merged: bool
    error: str | None = None


class DevOpsAgent:
    def merge(
        self,
        task_id: str,
        repo_dir: str,
        branch_name: str,
        target: str = "main",
    ) -> DevOpsResult:
        try:
            git_ops.merge_branch(repo_dir, branch_name, target=target)
            return DevOpsResult(task_id=task_id, merged=True)
        except git_ops.GitOpsError as exc:
            return DevOpsResult(task_id=task_id, merged=False, error=str(exc))