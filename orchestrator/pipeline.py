"""
orchestrator/pipeline.py

Sequential orchestration for the Phase 2 agent chain — direct function
calls through a shared TaskContext, not Redis pub/sub (build spec
section 3: pub/sub earns its complexity when agents are separate
concurrent services, which Phase 2 doesn't have).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from agents.pm import PMAgent, TaskSpec
from agents.architect import ArchitectAgent, DesignDecision
from agents.engineer import EngineerAgent, ImplementationAttempt
from agents.qa import QAAgent, QAResult
from agents.reviewer import ReviewerAgent, ReviewResult
from agents.devops import DevOpsAgent, DevOpsResult
import git_ops


@dataclass
class TaskContext:
    task_id: str
    feature_request: str
    task_spec: TaskSpec | None = None
    design_decision: DesignDecision | None = None
    branch_name: str | None = None
    implementation: ImplementationAttempt | None = None
    qa_result: QAResult | None = None
    review: ReviewResult | None = None
    devops: DevOpsResult | None = None


def _read_repo_context(repo_dir: str, max_chars: int = 4000) -> str:
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
    ctx.implementation = engineer.implement(ctx.task_spec, ctx.design_decision, repo_context, repo_dir)
    print(f"[pipeline] Engineer ({ctx.implementation.model_used}) produced "
          f"{len(ctx.implementation.changed_files)} file(s), "
          f"verbalized_confidence={ctx.implementation.verbalized_confidence:.2f}")

    if not ctx.implementation.changed_files:
        print("[pipeline] WARNING: Engineer produced no parseable file changes after revisions. Stopping here.")
        return ctx

    ctx.branch_name = f"praxis/{task_id}"
    git_ops.create_branch(repo_dir, ctx.branch_name)
    git_ops.write_files(repo_dir, ctx.implementation.changed_files)
    git_ops.commit(repo_dir, ctx.task_spec.pr_description)
    print(f"[pipeline] Committed to branch {ctx.branch_name}")

    qa = QAAgent()
    ctx.qa_result = qa.test(task_id=task_id, repo_dir=repo_dir)
    er = ctx.qa_result.execution_result
    print(f"[pipeline] QA: {er.tests_passed}/{er.tests_collected} passed, "
          f"pass_fraction={er.pass_fraction:.2f}, succeeded={ctx.qa_result.passed}")

    if er.tests_collected == 0:
        print("[pipeline] [diagnostic] zero tests collected:")
        print(f"    exit_code={er.exit_code} timed_out={er.timed_out}")
        print(f"    stdout: {er.stdout.strip()[:1500]!r}")
        print(f"    stderr: {er.stderr.strip()[:1500]!r}")
        print(f"    container_error: {er.container_error!r}")

    reviewer = ReviewerAgent()
    qa_summary = f"{er.tests_passed}/{er.tests_collected} passed"
    ctx.review = reviewer.review(
        task_id=task_id,
        repo_dir=repo_dir,
        qa_passed=ctx.qa_result.passed,
        qa_summary=qa_summary,
    )
    print(f"[pipeline] Reviewer verdict: {ctx.review.verdict} — {ctx.review.comments}")

    if ctx.review.verdict != "approve":
        print("[pipeline] Stopping here — Reviewer did not approve. DevOps does not run on unapproved changes.")
        return ctx

    devops = DevOpsAgent()
    ctx.devops = devops.merge(task_id=task_id, repo_dir=repo_dir, branch_name=ctx.branch_name)
    if ctx.devops.merged:
        print(f"[pipeline] DevOps merged {ctx.branch_name} into main. "
              f"Pipeline complete — this task went through all six agents for real.")
    else:
        print(f"[pipeline] DevOps merge FAILED: {ctx.devops.error}")

    return ctx