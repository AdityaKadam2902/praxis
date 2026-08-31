# Praxis — Phase 0 Build Spec
### Grounding Substrate: Sandboxed Execution + Single Agent + Outcome-Grounded Calibration
### Target: $0 cost, single machine, 8GB+ VRAM GPU

---

## Goal of Phase 0

Prove one thing, cheaply, before building anything else: **outcome-grounded (3-way) calibration produces a measurably better Brier score than verbalized+behavioral (2-way) calibration.** Everything after Phase 0 is scaffolding around this result. If it doesn't hold up, the whole differentiator needs rethinking — better to find that out with one agent than six.

---

## 1. Local Stack (all free)

| Component | Choice | Runs as |
|---|---|---|
| Inference | Ollama — `qwen2.5:7b` (fast tier), `qwen2.5:14b` (heavy tier) | Native process or Docker |
| Orchestration API | FastAPI | Docker |
| Graph DB | Kuzu (embedded, no server needed) | Local file, mounted volume |
| Relational DB | PostgreSQL 16 + pgvector | Docker |
| Task queue / pub-sub | Redis 7 | Docker |
| Sandboxed execution | Docker containers, `--network none`, non-root, CPU/memory-limited | Docker-in-Docker or sibling containers via mounted socket |
| Git operations | Local git + GitHub free tier (private repo, free Actions minutes) | CLI |
| Frontend (stub for now) | Vue3/Quasar — minimal, just enough to view task results | Dev server, no deploy yet |

Everything runs via a single `docker-compose.yml` on your machine. No cloud spend anywhere in Phase 0.

---

## 2. Folder Structure

```
praxis/
├── docker-compose.yml
├── orchestrator/                 # FastAPI app
│   ├── main.py
│   ├── routing.py                # model-tier selection logic
│   ├── calibration/
│   │   ├── verbalized.py
│   │   ├── behavioral.py
│   │   ├── outcome.py
│   │   └── fusion.py             # the 3-way vs 2-way comparison lives here
│   └── agents/
│       └── engineer.py           # single agent for Phase 0
├── sandbox/
│   ├── Dockerfile.runner         # ephemeral execution image
│   └── executor.py               # spins up a container, runs code, captures result
├── graph/
│   └── schema.py                 # Kuzu node/edge definitions
├── db/
│   └── models.py                 # Postgres models: tasks, agents, brier_scores
├── benchmark/
│   └── tasks/                    # ~20-30 small, self-contained coding tasks with known-good tests
└── frontend/                     # Vue3/Quasar, minimal task viewer
```

---

## 3. The Sandbox Executor (the piece that unlocks everything)

Minimal viable version:

1. Agent produces code + a self-reported confidence score (verbalized signal).
2. `executor.py` writes the code into a throwaway Docker container:
   - `--network none` (no internet access — prevents exfiltration and nondeterministic network-dependent tests)
   - `--memory 512m --cpus 1` (resource caps)
   - runs as non-root user
   - has a hard wall-clock timeout (e.g. 30s)
3. Container runs the task's test suite (pytest, or whatever fits the benchmark task).
4. Capture: exit code, stdout/stderr, pass/fail count, wall time.
5. Container is destroyed immediately after — nothing persists between runs.
6. This result *is* the outcome signal — no model involved in producing it, which is exactly why it's trustworthy in a way self-reported confidence isn't.

---

## 4. The Benchmark Task Set

You need ~20-30 small, self-contained coding tasks with a known-correct test suite, spanning a spread of difficulty (simple CRUD function → off-by-one-prone logic → concurrency edge case). Don't write these from scratch — pull a subset of **HumanEval** or **MBPP** (both free, open, designed exactly for this) to start, then add a few hand-written ones that match the kind of work you actually want Praxis to do later (repo-shaped tasks, not leetcode-shaped). This gives you an objective, external pass/fail signal for free, on day one, with zero labeling effort.

---

## 5. The Fusion Comparison (the actual experiment)

For each task:
- `verbalized_confidence` = agent's self-reported probability of correctness
- `behavioral_confidence` = derived from revision count + hedging-word frequency in the agent's reasoning trace
- `outcome_confidence` = 1.0 if tests passed in sandbox, scaled by pass-fraction if partial

Run two fusion models side by side on the same task set:
- **2-way**: `predicted = f(verbalized, behavioral)` — simple weighted average or logistic regression
- **3-way**: `predicted = f(verbalized, behavioral, outcome)` — same regression, one more input

Score both against **actual ground truth** (did the code really pass the held-out test suite, which the agent never sees, only a subset it can run against itself): `Brier = mean((predicted - actual)²)`.

Lower Brier score wins. This one number is Phase 0's pass/fail gate for the whole project thesis.

---

## 6. Kuzu Schema (minimal, for Phase 0)

```
Node: Agent(id, model_name, tier)
Node: Task(id, type, difficulty, benchmark_source)
Node: Attempt(id, verbalized_conf, behavioral_conf, outcome_conf, fused_2way, fused_3way, brier_2way, brier_3way, timestamp)

Edge: (Agent)-[:MADE]->(Attempt)
Edge: (Attempt)-[:ON]->(Task)
```

This is deliberately small. Don't build the full ADR/decision-graph schema yet — that's Phase 3. Phase 0 only needs enough graph structure to query "show me this agent's Brier score trend over time by task type."

---

## 7. What "Done" Looks Like for Phase 0

- [ ] One agent (Engineer, `qwen2.5:7b`/`14b` routed by task complexity) runs against 20-30 benchmark tasks
- [ ] Every attempt executes in the sandbox, real pass/fail captured
- [ ] Both 2-way and 3-way fusion scores computed and logged per attempt
- [ ] A simple script/notebook comparing aggregate Brier scores across the two fusion methods
- [ ] Result written down honestly, even if 3-way doesn't beat 2-way on this small sample — that's still a real finding that shapes Phase 1

Only once this is done do you move to Phase 1 (still single-agent, but now the router picks between the two Ollama tiers based on task complexity) and eventually Phase 2 (the other five agents).

---

## 8. Time-box

This is small enough to be a weekend-to-week project, not a month. If Phase 0 is taking longer than that, it's a sign the sandbox executor or the benchmark harness has scope-crept — both should stay minimal. The interesting work is in the calibration math, not the plumbing.