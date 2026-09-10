"""
orchestrator/pipeline.py

Sequential orchestration for the Phase 2 agent chain — direct function
calls through a shared TaskContext, not Redis pub/sub. Per the build
spec section 3: pub/sub earns its complexity when agents are separate
concurrent services, which Phase 2 doesn't have yet. This is the same
execution model as Phase 0's benchmark/run_benchmark.py, just extended
to six stages instead of one.

Currently wires PM -> Architect. Engineer/QA/Reviewer/DevOps stages are
explicit placeholders (raise NotImplementedError) rather than silently
skipped — next in the build order, not yet built.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from agents.pm import PMAgent, TaskSpec
from agents.architect import ArchitectAgent, DesignDecision
from agents.engineer import EngineerAgent, ImplementationAttempt
import git_ops


@dataclass
class TaskContext:
    task_id: str
    feature_request: str
    task_spec: TaskSpec | None = None
    design_decision: DesignDecision | None = None
    branch_name: str | None = None
    implementation: ImplementationAttempt | None = None  # holds changed_files + calibration data
    test_result: object | None = None                              # set by QA (not yet built)
    review_verdict: str | None = None                              # set by Reviewer (not yet built)
    review_comments: str | None = None
    merged: bool = False                                            # set by DevOps (not yet built)


def _read_repo_context(repo_dir: str, max_chars: int = 4000) -> str:
    """
    Flatten the repo's .py files into a single string for Architect to
    read. Simple and crude by design for Phase 2's small seed repo —
    revisit (e.g. only include files relevant to the task) if/when a
    larger seed repo makes the full-dump approach too slow or too big for
    the model's context.
    """
    chunks = []
    total = 0
    for py_file in sorted(Path(repo_dir).rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(repo_dir)
        content = py_file.read_text(encoding="utf-8")
        chunk = f"--- {rel} ---\n{content}\n"
        if total + len(chunk) > max_chars:
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n".join(chunks)


def run_pipeline(feature_request: str, repo_dir: str) -> TaskContext:
    """
    repo_dir must already be a cloned+branched working copy — this
    function doesn't call git_ops.clone_seed_repo/create_branch itself,
    since branch creation happens after PM has scoped the task (needs
    task_id for the branch name), not before. Caller sets up the repo,
    this orchestrates the agent chain against it.
    """
    task_id = str(uuid.uuid4())[:8]
    ctx = TaskContext(task_id=task_id, feature_request=feature_request)

    pm = PMAgent()
    ctx.task_spec = pm.scope(task_id=task_id, feature_request=feature_request)
    print(f"[pipeline] PM scoped: task_type={ctx.task_spec.task_type} "
          f"difficulty={ctx.task_spec.difficulty}")

    architect = ArchitectAgent()
    repo_context = _read_repo_context(repo_dir)
    ctx.design_decision = architect.decide(ctx.task_spec, repo_context)
    print(f"[pipeline] Architect decided, target_files={ctx.design_decision.target_files}")
    print(f"[pipeline] decision: {ctx.design_decision.decision_text}")

    engineer = EngineerAgent()
    ctx.implementation = engineer.implement(ctx.task_spec, ctx.design_decision, repo_context)
    print(f"[pipeline] Engineer ({ctx.implementation.model_used}) produced "
          f"{len(ctx.implementation.changed_files)} file(s), "
          f"verbalized_confidence={ctx.implementation.verbalized_confidence:.2f}")

    if not ctx.implementation.changed_files:
        # implement()'s own revision loop already tried to recover from
        # this; if it still comes back empty after max_revisions, don't
        # pretend there's something to commit — surface it plainly rather
        # than committing an empty change and letting QA/Reviewer deal
        # with a silently-nonexistent diff.
        print("[pipeline] WARNING: Engineer produced no parseable file changes after revisions. Stopping here.")
        return ctx

    ctx.branch_name = f"praxis/{task_id}"
    git_ops.create_branch(repo_dir, ctx.branch_name)
    git_ops.write_files(repo_dir, ctx.implementation.changed_files)
    git_ops.commit(repo_dir, ctx.task_spec.pr_description)
    print(f"[pipeline] Committed to branch {ctx.branch_name}")

    # --- QA/Reviewer/DevOps stages: not yet built ---
    print(
        "[pipeline] Stopping here — QA/Reviewer/DevOps aren't wired in yet "
        "(next in the build order). PM, Architect, and Engineer ran for "
        "real; the branch and commit above are real, inspectable state."
    )
    return ctx