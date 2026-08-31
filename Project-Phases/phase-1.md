# Praxis — Phase 2 Build Spec (v2 — gaps resolved)
### Multi-Agent Org + Trust-Based Routing

---

## Status coming in

Phase 0/1 closed — see `README.md` section 6. Infrastructure validated
end to end (sandbox execution, held-out grounding, 3-way fusion, Kuzu
logging, model-agnostic routing); thesis directionally supported but not
stress-tested, because isolated single-function tasks didn't produce
agent mistakes to catch.

**This version resolves four gaps found in review of v1** before any
Phase 2 code gets written:

1. No repo-level grounding mechanism existed for multi-file tasks
2. No git operations wrapper existed for Reviewer/DevOps to act on
3. Redis pub/sub vs sequential calls was never decided
4. PM's output was missing the metadata the router needs

Resolutions below; build order in section 8 reflects them.

---

## 1. Gap resolution: Repo-Grounded Execution

Phase 0's `SandboxExecutor`/`LocalExecutor` only accept a single
`solution_code` + `test_code` string pair — no notion of a repo, multiple
files, or a patch. Phase 2 needs grounding against a small seed repo with
its own existing tests.

**Design decision: full-file replacement, not diffs, for the grounding
step.** Engineer still outputs complete file contents for each file it
touches (matching its existing Phase 0 output style), not a unified diff.
Diff generation happens *separately*, only for Reviewer's benefit (see
section 3) — grounding correctness doesn't need to go through diff/patch
application at all, which is a whole extra failure surface (patches can
fail to apply cleanly) that Phase 2 doesn't need to take on.

New module, same shape as Phase 0's sandbox pattern:

```
sandbox/repo_executor.py   — copies seed repo to a temp dir, writes each
                              changed file, runs the repo's own test
                              command, returns ExecutionResult (reused
                              dataclass from Phase 0, no changes needed)
sandbox/repo_local.py      — local/no-Docker variant, mirrors
                              local_executor.py's pattern
```

Both reuse `sandbox/pytest_output.py` for parsing — no duplication there.
`sandbox/factory.py` gets a second function, `get_repo_executor()`,
following the same `PRAXIS_SANDBOX` env var.

**Seed repo gets built now, not deferred.** v1 said "build it once the
agent chain works end to end" — that was backwards; QA can't function
without it, so it's a section 8 build-order item, early, not an
afterthought.

---

## 2. Gap resolution: Git Operations Wrapper

New module: `orchestrator/git_ops.py` — thin subprocess wrapper, local
git only for Phase 2 (resolves v1's open GitHub-API-vs-local question:
**local-only**, per the earlier reasoning that it's the cheaper way to
prove the workflow shape before taking on a real GitHub dependency).

```python
# orchestrator/git_ops.py — functions, not a class, matches the
# functional style already used in sandbox/pytest_output.py

def clone_seed_repo(seed_path: str, work_dir: str) -> None: ...
def create_branch(repo_dir: str, branch_name: str) -> None: ...
def write_files(repo_dir: str, files: dict[str, str]) -> None: ...
def commit(repo_dir: str, message: str) -> str: ...          # returns commit hash
def diff_against(repo_dir: str, base_ref: str = "main") -> str: ...
def merge_branch(repo_dir: str, branch_name: str, target: str = "main") -> None: ...
```

This is what actually unblocks Reviewer (needs `diff_against` to have
something to read) and DevOps (needs `merge_branch` to have something to
do). Neither agent is meaningfully implementable without this existing
first — hence it's step 1 in the build order, ahead of any agent file.

---

## 3. Gap resolution: Sequential calls, not Redis pub/sub (for now)

**Decision: Phase 2 agents run sequentially, in one process, via direct
function calls through a shared `TaskContext` object — not Redis
pub/sub.**

Reasoning: pub/sub earns its complexity when agents are separate
concurrent services. Phase 2 doesn't have that yet — it's six functions
called in order, same execution model as Phase 0's `run_benchmark.py`.
Redis pub/sub in that context adds a real risk (fire-and-forget delivery
— an event published with no subscriber listening is silently lost) for
zero benefit. Building it now would be solving a distribution problem
Phase 2 doesn't have.

```python
# orchestrator/pipeline.py — new module, the Phase 2 equivalent of
# benchmark/run_benchmark.py's orchestration role

@dataclass
class TaskContext:
    task_id: str
    feature_request: str
    task_type: str | None = None       # set by PM
    difficulty: str | None = None      # set by PM
    design_decision: str | None = None # set by Architect
    branch_name: str | None = None
    changed_files: dict[str, str] = field(default_factory=dict)  # set by Engineer
    test_result: "ExecutionResult | None" = None  # set by QA
    review_verdict: str | None = None  # set by Reviewer: approve | request_changes
    review_comments: str | None = None
    merged: bool = False               # set by DevOps

def run_pipeline(feature_request: str) -> TaskContext:
    ctx = TaskContext(task_id=..., feature_request=feature_request)
    ctx = pm.scope(ctx)
    ctx = architect.decide(ctx)
    ctx = engineer.implement(ctx)
    ctx = qa.test(ctx)
    ctx = reviewer.review(ctx)
    if ctx.review_verdict == "approve":
        ctx = devops.merge(ctx)
    return ctx
```

Redis stays in `docker-compose.yml` — not removed, just not wired into
Phase 2's actual control flow. Revisit pub/sub if/when a later phase
needs agents running as genuinely separate, concurrent processes.

---

## 4. Gap resolution: PM output includes routing metadata

PM's output contract, made explicit (v1 only said "task list, PR
description" — too vague for what the router in section 6 needs):

```python
@dataclass
class TaskSpec:
    task_id: str
    task_type: str      # e.g. "bug_fix", "feature_add", "refactor"
    difficulty: str      # "simple" | "medium" | "hard" — PM's estimate
    scoped_description: str
    pr_description: str
```

`task_type`/`difficulty` map directly onto the fields Kuzu's `Task` node
already has (`graph/schema.py` — no schema change needed there, it was
already designed with this in mind). This is what lets the router in
section 6 bucket calibration history correctly, and it's also what feeds
Phase 2's cold-start fallback (same difficulty-based default Phase 0
used, until enough attempts accumulate per task_type).

---

## 5. Scope decision: calibration stays scoped to Engineer

Related gap worth naming explicitly, found while resolving the schema
question: **Phase 2 does not extend the 3-way calibration/fusion engine
to PM, Architect, Reviewer, or DevOps.** Their work has no clean
ground-truth signal the way code-passing-tests does — "was this task
breakdown good" or "was this architectural decision right" aren't things
the sandbox can verify. Building calibration for them now would mean
inventing a fake outcome signal, which would quietly undermine the one
part of this system that's actually rigorously grounded.

Kuzu's `Attempt` node gets one small addition — a `stage` property
(`"engineer"` for now, room for others later) — so the schema doesn't
need to change again if grounded calibration for other agents becomes
possible later (e.g., once Phase 3's ADR graph exists, an Architect
decision that later gets reverted becomes a real, gradable outcome).
Not built now — just not architecturally foreclosed.

---

## 6. Trust-Based Router — unchanged from v1, now correctly scoped

Replaces `EngineerAgent._select_model`'s hardcoded difficulty check with
one that queries Kuzu for the Engineer's real calibration history on the
specific `(task_type, difficulty)` combination — using the `task_type`
PM now provides (gap 4's resolution) instead of a task having no type at
all, as Phase 0's ad hoc benchmark tasks did.

```python
def select_model_for_task(task_type: str, difficulty: str) -> str:
    # Query graph/schema.py's brier data for this (task_type, difficulty).
    # Route to whichever tier has the better (lower) mean brier_3way.
    # Cold start: fall back to Phase 0's difficulty-only default until
    # N attempts exist for this task_type — pick N once real data shows
    # how noisy small samples look, don't guess a number now.
    ...
```

---

## 7. Agent Roster (updated)

| Agent | Input | Output |
|---|---|---|
| PM | Feature request (text) | `TaskSpec` (task_type, difficulty, scoped description, PR description) |
| Architect | `TaskSpec` + repo context | Design decision (text) |
| Engineer | `TaskSpec` + design decision | `{filename: content}` dict — full files, not diffs |
| QA | Changed files | `ExecutionResult` from `repo_executor.py` |
| Reviewer | Changed files + `ExecutionResult` + `git_ops.diff_against()` output | approve / request_changes + comments |
| DevOps | Approved `TaskContext` | Merge result via `git_ops.merge_branch()` |

One file per agent under `orchestrator/agents/`, matching `engineer.py`'s
existing pattern (own system prompt, accepts `provider: Provider | None
= None` for consistency across all six).

---

## 8. Build Order (revised — grounding and git ops move first)

1. **`orchestrator/git_ops.py`** — git wrapper. Nothing downstream works without it.
2. **`sandbox/repo_executor.py` + `sandbox/repo_local.py`** — repo-level grounding. QA can't function without it.
3. **Seed repo** — small (3-5 files, a few existing tests). Built now, not deferred, since steps 1-2 need something to operate on to be tested themselves.
4. **`orchestrator/pipeline.py`** — the sequential `TaskContext` orchestration (section 3).
5. **`pm.py`, `architect.py`** — first two agents in the chain.
6. **`engineer.py` update** — change output shape from single `solution_code` string to `{filename: content}` dict; wire in the trust-based router from section 6.
7. **`qa.py`** — calls `repo_executor.py`.
8. **`reviewer.py`, `devops.py`** — use `git_ops.py`.
9. **End-to-end test**: one full feature request through all six agents against the seed repo.

---

## 9. What Phase 2 still deliberately excludes

Unchanged from v1: ADR/decision graph (Phase 3), human escalation UI
(Phase 4), cost governance dashboard (Phase 5, though `cost_log` table
stays scaffolded), real GitHub PRs (explicitly decided against for
Phase 2 in section 2, not just deferred without a reason this time).