"""
orchestrator/git_ops.py

Thin subprocess wrapper around the git CLI — local git only for Phase 2
(no GitHub API), per the Phase 2 build spec's explicit decision to prove
the branch/diff/merge workflow shape cheaply before taking on a real
GitHub dependency.

This is what unblocks Reviewer (needs diff_against to have something to
read) and DevOps (needs merge_branch to have something to do) — neither
was implementable before this existed.

Every subprocess call forces UTF-8 explicitly (encoding="utf-8",
errors="replace") rather than relying on the OS default — Phase 0 lost a
lot of time to exactly this class of bug on Windows (the 'charmap' codec
error), so it's handled here from the start instead of discovered again.

Requires git installed and on PATH. Not checked/enforced here — if it's
missing, subprocess.run raises FileNotFoundError, which is a clear
enough signal on its own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitOpsError(RuntimeError):
    """Raised when a git command fails, with the real stderr attached."""


def _run_git(args: list[str], cwd: str | Path) -> str:
    """
    Run a git command, forcing UTF-8 decoding, and raise with the actual
    stderr on failure rather than a bare non-zero-exit-code error.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise GitOpsError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def clone_seed_repo(seed_path: str, work_dir: str) -> None:
    """
    Copy the seed repo's files into a fresh working directory and
    initialize a new git repo there with an initial commit.

    Uses a plain copy + `git init` rather than `git clone`, so the seed
    repo itself never needs its own .git history — important because the
    seed repo lives inside the main praxis project, which is itself a
    git repo. A nested .git folder inside a tracked repo behaves like an
    accidental submodule and causes exactly the kind of confusing git
    state this project has already spent enough time debugging.
    """
    import shutil

    shutil.copytree(seed_path, work_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
    _run_git(["init", "-q"], cwd=work_dir)
    _run_git(["branch", "-m", "main"], cwd=work_dir)  # normalize default branch name
    _run_git(["add", "-A"], cwd=work_dir)
    _run_git(["commit", "-q", "-m", "Initial seed repo state"], cwd=work_dir)


def create_branch(repo_dir: str, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name], cwd=repo_dir)


def write_files(repo_dir: str, files: dict[str, str]) -> None:
    """
    Write each {relative_path: content} entry into repo_dir, creating
    parent directories as needed. UTF-8 explicit, same reasoning as the
    subprocess calls above.
    """
    for rel_path, content in files.items():
        target = Path(repo_dir) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def commit(repo_dir: str, message: str) -> str:
    """Stage everything and commit. Returns the new commit hash."""
    _run_git(["add", "-A"], cwd=repo_dir)
    _run_git(["commit", "-m", message], cwd=repo_dir)
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def diff_against(repo_dir: str, base_ref: str = "main") -> str:
    """
    Diff the current branch's HEAD against base_ref. base_ref defaults to
    "main" — if the seed repo actually uses "master" (older git default),
    pass that explicitly. Not auto-detected here; keep this simple until
    it's a real problem.
    """
    return _run_git(["diff", f"{base_ref}...HEAD"], cwd=repo_dir)


def merge_branch(repo_dir: str, branch_name: str, target: str = "main") -> None:
    """Checkout target, merge branch_name into it. No conflict resolution — a
    real conflict raises GitOpsError with git's own message, which is enough
    for Phase 2's scope (no auto-resolution logic needed yet)."""
    _run_git(["checkout", target], cwd=repo_dir)
    _run_git(["merge", "--no-ff", branch_name, "-m", f"Merge {branch_name} into {target}"], cwd=repo_dir)


def current_branch(repo_dir: str) -> str:
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)