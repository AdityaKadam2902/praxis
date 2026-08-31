# Seed Repo — Praxis Phase 2

A tiny, deliberately incomplete calculator app used as the grounding
target for Phase 2's multi-agent pipeline (PM → Architect → Engineer →
QA → Reviewer → DevOps).

**Not a git repo itself** — `orchestrator/git_ops.clone_seed_repo()`
copies these files into a fresh temp directory and initializes git there
on demand, per task. Keeping this folder plain avoids nesting a `.git`
inside the main `praxis` project's own git repo.

## Structure
- `app/calculator.py` — add/subtract/multiply/divide. No `power` operation
  (deliberate — a natural target for a first feature-request task).
- `app/validators.py` — shared input validation.
- `tests/` — existing test suite; QA runs this (or a subset) after
  Engineer's changes are written and committed.

## Running tests directly (sanity check, not part of the pipeline)
```
cd seed_repo
pytest -q
```
