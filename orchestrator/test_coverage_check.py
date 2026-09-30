"""
orchestrator/test_coverage_check.py

Structural (AST-based) check that new public functions/classes Engineer
introduces actually have SOME test referencing them by name.

Added after two real incidents in back-to-back runs:
1. Engineer added sum() calling an undefined builtins.sum() with zero
   tests referencing it — QA's 8/8 pass never touched the bug because
   no test ever called sum() at all.
2. Reviewer then hallucinated an identically-shaped but FALSE bug report
   against a correctly-implemented power() function — and because
   power() also had zero tests, there was no execution evidence on
   either side to check the claim against.

A prompt instruction telling Engineer to "always write tests, even if
Architect doesn't ask" was tried first and did not hold — Architect's
decision explicitly said "no changes to tests are required" and Engineer
complied anyway. This is the structural version: a hard, code-level
check rather than trusting the model to follow an instruction, matching
the same principle behind Reviewer's auto-reject-on-QA-fail rule.

Deliberately crude (name mentioned anywhere in test file text, not
verified to be a real, correct call) — the goal isn't to prove test
quality, it's to catch the specific, now-twice-observed failure mode of
a new function shipping with literally zero test awareness of its
existence. Verified against both real incidents plus a negative control
(a new function that does have a real test isn't flagged).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


def _extract_public_top_level_names(source: str) -> set[str]:
    """
    Top-level function/class names not starting with underscore. Returns
    an empty set (not an error) on a parse failure — a syntax error in
    Engineer's output is a different problem this check doesn't need to
    also report.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
    return names


def _is_test_file(path: str) -> bool:
    filename = Path(path).name
    return filename.startswith("test_") or "/tests/" in path.replace("\\", "/")


def is_test_only_output(changed_files: dict[str, str]) -> bool:
    """
    True if Engineer's output contains only test file(s) and zero source
    files — added after two real, repeated incidents where a heavily
    retried call (multiple 429s / empty-content loops in a row) produced
    exactly one lone test file (test_parser.py once, test_ui.py once)
    with no corresponding implementation at all. QA correctly caught
    both as 0/N passed and Reviewer correctly auto-rejected them, but
    only after the full pipeline ran and wasted the QA/Reviewer calls —
    catching this here, in Engineer's own revision loop, is cheaper and
    faster than waiting for QA to notice the same thing.
    """
    if not changed_files:
        return False
    return all(_is_test_file(path) for path in changed_files)


def find_untested_new_functions(
    repo_dir: str,
    changed_files: dict[str, str],
) -> list[tuple[str, str]]:
    """
    Returns [(file_path, name), ...] for every new public top-level
    function/class Engineer introduced in a non-test file that isn't
    mentioned by name in any test file's content (existing or newly
    changed).

    Must be called BEFORE the changed files are written to repo_dir,
    since it reads the pre-change content directly from disk to compute
    what's actually new.
    """
    test_content_blobs = []
    for path, content in changed_files.items():
        if _is_test_file(path):
            test_content_blobs.append(content)
    for test_file in Path(repo_dir).rglob("test_*.py"):
        rel = str(test_file.relative_to(repo_dir)).replace("\\", "/")
        if rel not in changed_files:
            test_content_blobs.append(test_file.read_text(encoding="utf-8"))
    combined_test_text = "\n".join(test_content_blobs)

    missing: list[tuple[str, str]] = []

    for path, new_content in changed_files.items():
        if _is_test_file(path):
            continue

        original_path = Path(repo_dir) / path
        original_content = original_path.read_text(encoding="utf-8") if original_path.exists() else ""

        old_names = _extract_public_top_level_names(original_content)
        new_names = _extract_public_top_level_names(new_content)
        added_names = new_names - old_names

        for name in added_names:
            if not re.search(rf"\b{re.escape(name)}\b", combined_test_text):
                missing.append((path, name))

    return missing