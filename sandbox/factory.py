"""
sandbox/factory.py

One env var (PRAXIS_SANDBOX) decides the backend for both single-function
grounding (get_executor, Phase 0) and repo-level grounding (
get_repo_executor, Phase 2) — one setting for the whole project, not two
to keep in sync.
"""

from __future__ import annotations

import os


def get_executor():
    choice = os.environ.get("PRAXIS_SANDBOX", "docker").lower()
    print(f"[sandbox] PRAXIS_SANDBOX resolved to: '{choice}'")

    if choice == "docker":
        from sandbox.executor import SandboxExecutor
        return SandboxExecutor()

    if choice == "local":
        from sandbox.local_executor import LocalExecutor
        print(
            "[warning] PRAXIS_SANDBOX=local — running agent code directly on "
            "this machine with NO isolation (no network block, no resource "
            "caps, no sandboxing). Fine for your own reviewed seed tasks. "
            "Switch to PRAXIS_SANDBOX=docker before running anything you "
            "haven't read yourself."
        )
        return LocalExecutor()

    raise ValueError(f"Unknown PRAXIS_SANDBOX '{choice}'. Expected: docker or local.")


def get_repo_executor():
    """Phase 2 equivalent of get_executor(), for repo-level grounding."""
    choice = os.environ.get("PRAXIS_SANDBOX", "docker").lower()
    print(f"[sandbox] (repo) PRAXIS_SANDBOX resolved to: '{choice}'")

    if choice == "docker":
        from sandbox.repo_executor import RepoSandboxExecutor
        return RepoSandboxExecutor()

    if choice == "local":
        from sandbox.repo_local import RepoLocalExecutor
        print(
            "[warning] PRAXIS_SANDBOX=local — running repo-level test suites "
            "directly on this machine with NO isolation. Fine for your own "
            "reviewed seed repo; switch to PRAXIS_SANDBOX=docker before "
            "running anything containing code you haven't reviewed."
        )
        return RepoLocalExecutor()

    raise ValueError(f"Unknown PRAXIS_SANDBOX '{choice}'. Expected: docker or local.")