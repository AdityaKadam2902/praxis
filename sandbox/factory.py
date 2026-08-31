"""
sandbox/factory.py

Mirrors providers/factory.py's pattern: one env var decides the backend,
nothing else in the codebase needs to know or care which one is active.

PRAXIS_SANDBOX=docker  -> SandboxExecutor (isolated, requires Docker running)
PRAXIS_SANDBOX=local   -> LocalExecutor (no isolation, no Docker needed)

Defaults to docker — local must be an explicit opt-in, not an accidental
fallback, given the isolation tradeoff documented in local_executor.py.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Loads .env independently, rather than relying on providers/factory.py
# having already loaded it first (previously true only because
# EngineerAgent() happens to run before get_executor() in
# run_benchmark.py — a fragile, implicit ordering dependency). Safe to
# call twice; python-dotenv is idempotent.
load_dotenv()


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
    """
    Phase 2 equivalent of get_executor(), for repo-level grounding
    (RepoLocalExecutor / RepoSandboxExecutor) instead of single-function
    grounding. Same PRAXIS_SANDBOX env var controls both — one setting
    for the whole project, not two to keep in sync.
    """
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