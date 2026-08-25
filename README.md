# Praxis — Phase 0

Grounding substrate + single-agent, outcome-grounded calibration.
Goal: prove 3-way fusion (verbalized × behavioral × outcome) beats 2-way
fusion (verbalized × behavioral) on Brier score, before building the other
five agents on top of it.

Full context: `praxis-architecture-spec.md` and `praxis-phase0-build-spec.md`.

---

## 1. Prerequisites (all free)

- Docker + Docker Compose
- Python 3.11+ (for running the benchmark script locally, outside Docker, which is the simplest Phase 0 workflow)
- A model provider — pick one:
  - **Ollama** (default, fully local/offline) — install from [ollama.com](https://ollama.com)
  - **Groq** (free tier, fast) — free key at [console.groq.com/keys](https://console.groq.com/keys)
  - **Gemini** (free tier) — free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## 1a. Choosing a provider

```bash
cp .env.example .env
```

Then edit `.env` and set `PRAXIS_PROVIDER` to `ollama`, `groq`, or `gemini`,
plus the matching API key if using Groq/Gemini. `.env` is gitignored — your
real keys never get committed. `providers/factory.py` loads it
automatically via `python-dotenv`, so nothing else needs to change.

Minimum required `.env` for Groq:
```
PRAXIS_PROVIDER=groq
GROQ_API_KEY=your_real_key_here   # 50+ chars, from console.groq.com/keys
PRAXIS_SANDBOX=local              # or docker, once you're set up for it
```
`GROQ_FAST_MODEL` / `GROQ_HEAVY_MODEL` are optional — only needed if the
defaults in `groq_provider.py` stop working (see note below).

Nothing else changes — `agents/engineer.py` and the calibration code don't
know or care which provider is active. Note: Groq/Gemini model names move
fast — if `generate()` errors with a model-not-found (404) message, don't
edit provider code. For Groq, set `GROQ_FAST_MODEL` / `GROQ_HEAVY_MODEL`
in `.env` to a current model from https://console.groq.com/docs/models —
no code change needed. Gemini model names aren't yet overridable this way;
update the constants in `providers/gemini_provider.py` if that one breaks.

One real tradeoff to know about: Groq/Gemini calls include network
round-trip time in `time_taken_seconds`, which feeds the behavioral
confidence signal. `run_benchmark.py` applies a rough 2.5x baseline
inflation for network providers to compensate — treat that as a heuristic,
not a measured correction, until you've logged real per-provider latency.

## 2. One-time setup

```bash
# If using Ollama (skip if using Groq/Gemini):
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama serve   # leave running in its own terminal

# Build the sandbox execution image (needed regardless of provider —
# sandboxing is about the CODE the model writes, not the model itself)
docker build -f sandbox/Dockerfile.runner -t praxis-sandbox-runner ./sandbox

# Start Postgres + Redis (orchestrator API isn't needed for the Phase 0
# benchmark script itself — it talks to Ollama/Docker/Kuzu directly — but
# bring the stack up now since Phase 1 will need it)
docker compose up -d postgres redis

# Python deps for running the benchmark locally
cd orchestrator
pip install -r requirements.txt
cd ..
```

## 3. Run the Phase 0 experiment

```bash
python benchmark/run_benchmark.py
```

Run this from the `praxis/` project root (works the same on Windows/PowerShell,
macOS, or Linux — the script adds the right directories to its own import
path at runtime, so no `PYTHONPATH` setup is needed).

This will, for each seed task:
1. Ask the Engineer agent to solve it via Ollama
2. Score behavioral confidence from the response
3. Run the solution in a locked-down sandbox container against real tests
4. Score outcome confidence from the real pass/fail result
5. Update both the 2-way and 3-way fusion models and log Brier scores
6. Write everything to the Kuzu graph at `graph/kuzu_db/`

...then print the headline comparison.

## 4. Sanity-check the sandbox in isolation

Before running the full benchmark, it's worth confirming the sandbox itself
works:

```bash
cd sandbox
python executor.py
```

Should print `succeeded=True pass_fraction=1.00` for the built-in smoke test.

## 5. Known limitations to fix before trusting the Phase 0 result

- **Only 5 seed tasks** in `benchmark/tasks/seed_tasks.json`. The build spec
  calls for 20-30. Extend with a HumanEval or MBPP subset (both free,
  open-licensed) before drawing real conclusions — 5 tasks is enough to
  confirm the pipeline runs end to end, not enough to trust the Brier
  comparison.
- **`ground_truth == outcome`** in the current fusion call (see the note at
  the bottom of `orchestrator/calibration/fusion.py`). This mechanically
  favors 3-way fusion. Fix by splitting each task's tests into a
  visible subset (what the sandbox run sees) and a held-out subset (what
  ground truth is scored against) before treating results as conclusive.
- **pytest output parsing is regex-based** (`sandbox/executor.py`). Works
  for Phase 0's simple cases; swap for `pytest --json-report` if test
  output gets more complex.
- **Behavioral confidence baselines are hardcoded guesses**
  (`BASELINE_TIME_SECONDS` in `agents/engineer.py`). Phase 1 should compute
  these empirically from logged attempts instead.

## 6. Phase 0 result — CLOSED (Aug 2026)

**Verdict: methodology validated, thesis directionally supported, task genre limitation identified.**

Final clean run: 13 tasks (5 baseline + 8 adversarial), real held-out test
split (no `ground_truth == outcome` overlap), UTF-8 encoding fixed, model
routing verified via explicit diagnostic logging (`openai/gpt-oss-20b` on
every task, confirmed — not inferred from Brier arithmetic).

- `mean_brier_2way = 0.0417`, `mean_brier_3way = 0.0363` — 3-way fusion won
  on every full run once the methodology was actually clean.
- **But `outcome == ground_truth == 1.00` on all 13 tasks, every run,
  across two different model sizes** (Groq's 20b and 120b tiers both
  aced every task, including the 8 adversarial ones targeting closures,
  binary search boundaries, interval edge cases, etc.). Zero divergence
  between outcome and ground truth means the win, while real, is modest
  and mostly reflects the online fusion model's warm-up behavior — not a
  demonstrated case of catching a confidently-wrong agent.

**Honest conclusion:** isolated, well-specified single-function coding
tasks are not a strong test bed for outcome-grounded calibration, because
capable models — even smaller ones — are reliable on this exact genre of
problem (it's heavily represented in training data). This is a real
boundary condition worth remembering, not a failure of the experiment.
The infrastructure (sandbox execution, held-out test grounding, 3-way
fusion math, Kuzu logging, model-agnostic routing) is fully validated end
to end and ready to build on.

**Where real divergence is expected to show up:** Phase 2+ tasks involving
actual repo context, multi-file changes, ambiguous requirements, and
integration with existing code — the kind of work where even capable
models genuinely disagree with each other and with themselves. That's
where outcome-grounding is expected to earn its keep; Phase 0 didn't
disprove that, it just didn't have the right task shape to test it.

## 7. Next: Phase 2 — Multi-agent org + trust routing

Per the architecture spec, Phase 1 (single-agent calibration validation)
is effectively complete via the work above. Next is Phase 2: add
PM/Architect/QA/Reviewer/DevOps agents, wire them together via Redis
pub/sub handoffs, and build the trust-based router using the calibration
history now sitting in `graph/kuzu_db/` instead of the current static
difficulty-based `_select_model`.