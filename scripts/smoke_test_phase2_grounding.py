"""
scripts/smoke_test_phase2_grounding.py

Standalone verification of the Phase 2 grounding layer (git_ops.py +
sandbox/repo_local.py) against the real seed_repo, on your actual
machine — not just in dev-sandbox conditions. Run this once after
placing seed_repo/ and the corrected git_ops.py, before building the
agent pipeline on top of them.

Does NOT touch your real seed_repo/ folder — everything happens in a
throwaway temp directory, cleaned up at the end regardless of outcome.

Run from the praxis/ project root:
    python scripts/smoke_test_phase2_grounding.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

# Same sys.path pattern as benchmark/run_benchmark.py — no PYTHONPATH needed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ORCHESTRATOR_DIR = _PROJECT_ROOT / "orchestrator"
for _path in (_PROJECT_ROOT, _ORCHESTRATOR_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import git_ops
from sandbox.factory import get_repo_executor

SEED_REPO = str(_PROJECT_ROOT / "seed_repo")


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"Smoke test failed at: {label}")


def run() -> None:
    if not Path(SEED_REPO).exists():
        print(f"ERROR: seed_repo not found at {SEED_REPO}")
        print("Unzip seed_repo.zip into the project root first.")
        sys.exit(1)

    work_dir = Path(tempfile.mkdtemp(prefix="praxis_smoke_"))
    executor = get_repo_executor()

    try:
        print("\n1. Clone seed_repo into a fresh work dir...")
        git_ops.clone_seed_repo(SEED_REPO, str(work_dir))
        check("cloned successfully", work_dir.exists())
        check("default branch is 'main'", git_ops.current_branch(str(work_dir)) == "main")

        print("\n2. Run existing tests as-is...")
        result = executor.run(task_id="smoke-sanity", repo_dir=str(work_dir))
        print(f"    {result.tests_passed}/{result.tests_collected} passed")
        check("all 8 existing tests pass unmodified", result.tests_passed == 8 and result.tests_collected == 8)

        print("\n3. Confirm __pycache__ didn't get tracked as a dirty change...")
        status = git_ops._run_git(["status", "--porcelain"], cwd=str(work_dir))
        check("working tree clean after running tests", status == "")

        print("\n4. Simulate a feature-request task: add power() to calculator.py...")
        git_ops.create_branch(str(work_dir), "praxis/smoke-add-power")
        calc = (work_dir / "app" / "calculator.py").read_text(encoding="utf-8")
        calc += "\n\ndef power(a: float, b: float) -> float:\n    require_numbers(a, b)\n    return a ** b\n"
        tests = (work_dir / "tests" / "test_calculator.py").read_text(encoding="utf-8")
        tests += "\n\ndef test_power():\n    from app.calculator import power\n    assert power(2, 3) == 8\n"
        git_ops.write_files(str(work_dir), {
            "app/calculator.py": calc,
            "tests/test_calculator.py": tests,
        })
        git_ops.commit(str(work_dir), "Add power() operation")
        check("branch created and committed", git_ops.current_branch(str(work_dir)) == "praxis/smoke-add-power")

        print("\n5. QA re-runs tests on the branch...")
        result2 = executor.run(task_id="smoke-add-power", repo_dir=str(work_dir))
        print(f"    {result2.tests_passed}/{result2.tests_collected} passed")
        check("new feature + all existing tests pass together", result2.tests_passed == 9 and result2.tests_collected == 9)

        print("\n6. Reviewer's diff — should contain only the real change, no pycache noise...")
        diff = git_ops.diff_against(str(work_dir), "main")
        check("diff has no __pycache__/.pyc noise", "__pycache__" not in diff and ".pyc" not in diff)
        check("diff mentions the actual change", "power" in diff)

        print("\n7. DevOps merges...")
        git_ops.merge_branch(str(work_dir), "praxis/smoke-add-power", "main")
        check("merge succeeded, back on main", git_ops.current_branch(str(work_dir)) == "main")

        print("\nALL CHECKS PASSED — Phase 2 grounding layer verified on this machine.")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    run()