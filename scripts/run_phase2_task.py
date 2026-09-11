"""
scripts/run_phase2_task.py

Entry point for the Phase 2 pipeline (PM -> Architect -> Engineer -> QA,
Reviewer/DevOps not wired in yet). Clones a fresh, throwaway copy of
seed_repo/ per run — never touches your actual seed_repo/ folder — then
runs one feature request through the agent chain and prints the result.

Same sys.path setup as benchmark/run_benchmark.py, so no PYTHONPATH is
needed regardless of OS or shell.

Run from the project root:
    python scripts/run_phase2_task.py
    python scripts/run_phase2_task.py "your own feature request here"
"""

from __future__ import annotations

import sys
import shutil
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ORCHESTRATOR_DIR = _PROJECT_ROOT / "orchestrator"
for _path in (_PROJECT_ROOT, _ORCHESTRATOR_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import git_ops
from pipeline import run_pipeline

SEED_REPO = str(_PROJECT_ROOT / "seed_repo")

# Default request targets the deliberate gap in seed_repo/app/calculator.py
# (no power() operation) — see seed_repo/README.md.
DEFAULT_FEATURE_REQUEST = (
    "Add exponentiation support to the calculator. Users should be able "
    "to compute a raised to the power of b."
)


def main() -> None:
    feature_request = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FEATURE_REQUEST

    if not Path(SEED_REPO).exists():
        print(f"ERROR: seed_repo not found at {SEED_REPO}")
        print("Unzip seed_repo.zip into the project root first.")
        sys.exit(1)

    work_dir = Path(tempfile.mkdtemp(prefix="praxis_phase2_"))
    print(f"[runner] Feature request: {feature_request}")
    print(f"[runner] Working copy: {work_dir}\n")

    try:
        git_ops.clone_seed_repo(SEED_REPO, str(work_dir))
        ctx = run_pipeline(feature_request, str(work_dir))

        print("\n" + "=" * 60)
        print("PIPELINE RESULT")
        print("=" * 60)
        print(f"task_id: {ctx.task_id}")
        if ctx.task_spec:
            print(f"task_type: {ctx.task_spec.task_type}  difficulty: {ctx.task_spec.difficulty}")
        if ctx.implementation:
            print(f"files changed: {list(ctx.implementation.changed_files.keys())}")
        if ctx.qa_result:
            er = ctx.qa_result.execution_result
            print(f"QA: {er.tests_passed}/{er.tests_collected} passed, "
                  f"succeeded={ctx.qa_result.passed}")
        if ctx.review:
            print(f"Review: {ctx.review.verdict} — {ctx.review.comments}")
        if ctx.devops:
            print(f"DevOps: merged={ctx.devops.merged}" + (f" error={ctx.devops.error}" if ctx.devops.error else ""))
        print(f"\nWorking copy left in place for inspection: {work_dir}")
        print("(not cleaned up automatically — delete it manually when done reviewing)")

    except Exception:
        # On failure, still print the work_dir path so you can inspect
        # whatever partial git state exists — don't clean up on error,
        # that's exactly when you need to look at it.
        print(f"\n[runner] Failed — working copy preserved for inspection at: {work_dir}")
        raise


if __name__ == "__main__":
    main()