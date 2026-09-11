# Praxis

A grounded multi-agent software engineering system. Six agents (PM,
Architect, Engineer, QA, Reviewer, DevOps) work a feature request
against a real seed repo, producing a real branch, real commits, real
sandboxed test runs, and a real merge — with calibration built on
outcome-grounded signal (did the code actually pass its tests), not just
a model's self-reported confidence.

Full design reasoning: `praxis-architecture-spec.md`,
`praxis-phase0-build-spec.md`, `praxis-phase2-build-spec.md`.

---

## 1. Prerequisites

- Python 3.11+
- Git, installed and on PATH
- `pytest` installed in your environment (`pip install -r orchestrator/requirements.txt`) —
  required even for `PRAXIS_SANDBOX=local`, since that mode runs pytest directly on the host
- A model provider — Ollama (local, offline), Groq (free tier, fast), or Gemini (free tier)
- Docker, only if you plan to use `PRAXIS_SANDBOX=docker` (optional — `local` works without it)

## 2. Setup

```bash
cp .env.example .env
```

Edit `.env`:

```
PRAXIS_PROVIDER=groq            # ollama | groq | gemini
GROQ_API_KEY=your_real_key_here # https://console.groq.com/keys
GROQ_FAST_MODEL=openai/gpt-oss-20b
GROQ_HEAVY_MODEL=openai/gpt-oss-120b
PRAXIS_SANDBOX=local            # docker | local
```

Install dependencies:

```bash
pip install -r orchestrator/requirements.txt
```

## 3. Phase 0/1 — single-agent calibration benchmark

```bash
python benchmark/run_benchmark.py
```

Runs 13 seed tasks through a single Engineer agent, comparing 2-way
fusion (verbalized + behavioral confidence) against 3-way fusion (adding
a real, sandboxed outcome signal) via Brier score.

**Result (closed):** methodology fully validated — real held-out test
split, real UTF-8 handling, verified model routing. But `openai/gpt-oss-20b`
and even the 120b tier aced all 13 tasks across every clean run, so the
Brier comparison never got the divergence needed to stress-test the
thesis. Isolated, well-specified single-function tasks aren't a strong
test bed for outcome-grounded calibration — capable models are just
reliable on this genre of problem. Real divergence is expected to show
up in Phase 2's messier, multi-file, more ambiguous task shape instead.

## 4. Phase 2 — full six-agent pipeline

```bash
python scripts/run_phase2_task.py
python scripts/run_phase2_task.py "your own feature request"
```

Clones a fresh, throwaway copy of `seed_repo/` per run (never touches
the real folder), then runs PM → Architect → Engineer → QA → Reviewer →
DevOps against it.

**Status: working.** Completed successfully end to end, twice, with real
API calls, real git operations, real sandboxed test execution, and a
real merge. Two real production issues found and fixed along the way:

- **Rate limiting** — Groq free tier 429s. Fixed with retry-with-backoff
  in `providers/groq_provider.py`, honoring `Retry-After`.
- **Reasoning-model token exhaustion** — `openai/gpt-oss-20b` spent its
  full token budget on internal reasoning before producing output,
  returning `finish_reason=length` with empty content. Fixed by setting
  `max_tokens=4096` explicitly.

**Not yet stress-tested** — both successful runs used the same request
("add exponentiation support"). Worth trying ambiguous requests, requests
that should get rejected by Reviewer, and requests touching multiple
functions at once before treating this as fully proven.

Key design decisions (see `praxis-phase2-build-spec.md` for full reasoning):
- **Sequential orchestration, not Redis pub/sub** — direct function calls
  through a `TaskContext`, since Phase 2 doesn't have genuinely concurrent
  agent processes yet.
- **Full-file replacement, not diffs** — Engineer outputs complete file
  contents; diff generation happens separately for Reviewer's benefit only.
- **Local git only** — no GitHub API dependency yet, to prove the branch/
  diff/merge workflow shape cheaply first.
- **Calibration stays scoped to Engineer** — PM/Architect/Reviewer/DevOps
  don't have a clean ground-truth signal the way code-against-tests does,
  so extending 3-way fusion to them would mean inventing a fake outcome
  signal. Revisit once Phase 3's ADR graph makes an Architect decision
  that later gets reverted a real, gradable outcome.
- **Reviewer hard-rejects failing QA without calling the model** — a
  structural guarantee, not a prompt instruction the model could ignore.

## 5. Troubleshooting notes worth knowing

- **Kuzu PRIMARY KEY syntax**: this project's Kuzu 0.4.2 install only
  accepts a trailing `PRIMARY KEY (col)` clause, not inline
  `col TYPE PRIMARY KEY` — confirmed empirically via
  `scripts/diagnose_kuzu_variants.py`. `graph/schema.py` uses the
  working form.
- **Encoding**: every file write and subprocess call explicitly forces
  UTF-8 (`encoding="utf-8"`, `errors="replace"`) after an early incident
  where a Unicode character in model output crashed on Windows' default
  `cp1252` codec.
- **`PRAXIS_SANDBOX=local` requires `pytest` actually installed** — a
  missing dependency used to fail silently (Windows `WinError 2`) and
  get misread as a real 0/0 test result. `sandbox/pytest_output.py`'s
  `check_pytest_available()` now fails loudly at executor construction
  instead.

## 6. Next: Phase 3 — ADR / decision graph

Write Architect's decisions to Kuzu as queryable ADR nodes linked to the
task and files touched; have Architect query past decisions before
acting again, so a later task doesn't contradict an earlier
architectural choice on the same repo. Not started yet.