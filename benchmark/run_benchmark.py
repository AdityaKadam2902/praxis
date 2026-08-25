"""
benchmark/run_benchmark.py

The Phase 0 experiment, executed end to end:

  for each task:
    1. EngineerAgent solves it -> verbalized confidence + process data
    2. behavioral.py scores the process data -> behavioral confidence
    3. Sandbox runs the solution against a small VISIBLE test suite -> outcome confidence
    4. Sandbox separately runs the SAME solution against a larger HELD-OUT
       test suite the agent never saw -> ground_truth
    5. CalibrationFusionEngine scores 2-way vs 3-way fusion of outcome
       against ground_truth (genuinely independent signals now, not the
       same number twice)
    6. Everything gets written to Kuzu

  at the end: print the headline Brier score comparison.

Run from the project root — the script adds orchestrator/ to sys.path
itself, no PYTHONPATH setup needed:

    cd praxis
    python benchmark/run_benchmark.py

Prerequisites:
  - A configured provider (see .env / README) — Ollama, Groq, or Gemini
  - A configured sandbox (see .env) — Docker or local
  - graph/kuzu_db writable directory
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# Make both the project root (for sandbox/, graph/) and orchestrator/ (for
# agents/, calibration/, providers/) importable regardless of cwd, OS, or
# whether PYTHONPATH was set — this used to rely on `PYTHONPATH=.` being
# set manually (bash-only syntax, and even then only covered the project
# root, not orchestrator/). Doing it here removes that failure mode
# entirely, on Windows/PowerShell included.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ORCHESTRATOR_DIR = _PROJECT_ROOT / "orchestrator"
for _path in (_PROJECT_ROOT, _ORCHESTRATOR_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.engineer import EngineerAgent, BASELINE_TIME_SECONDS
from calibration.behavioral import compute_behavioral_confidence
from calibration.outcome import compute_outcome_confidence
from calibration.fusion import CalibrationFusionEngine
from sandbox.factory import get_executor
from graph.schema import init_schema, record_attempt

import kuzu

TASKS_PATH = Path(__file__).parent / "tasks" / "seed_tasks.json"
KUZU_DB_PATH = str(Path(__file__).parent.parent / "graph" / "kuzu_db")
AGENT_ID = "engineer_v0"


def load_tasks() -> list[dict]:
    with open(TASKS_PATH) as f:
        tasks = json.load(f)
    if len(tasks) < 20:
        print(
            f"[note] Running with {len(tasks)} seed tasks. The Phase 0 spec calls for "
            "~20-30 for a meaningful Brier comparison.\n"
        )
    return tasks


def run() -> None:
    tasks = load_tasks()

    engineer = EngineerAgent()
    executor = get_executor()
    fusion = CalibrationFusionEngine()

    db = init_schema(KUZU_DB_PATH)
    conn = kuzu.Connection(db)

    for task in tasks:
        task_id = task["task_id"]
        difficulty = task["difficulty"]
        baseline = BASELINE_TIME_SECONDS.get(difficulty, 30.0)

        print(f"--- {task_id} ({task['task_type']}, {difficulty}) ---")

        attempt = engineer.solve(task_id=task_id, prompt=task["prompt"], difficulty=difficulty)
        print(f"  model_used: {attempt.model_used}")

        # Network providers (Groq/Gemini) add round-trip latency that has
        # nothing to do with the model "struggling" — inflate the baseline
        # accordingly so the behavioral time signal isn't penalizing network
        # overhead. Rough heuristic, not measured — tighten this once you
        # have real latency numbers logged per provider.
        effective_baseline = baseline * 2.5 if attempt.network_call else baseline

        behavioral = compute_behavioral_confidence(
            reasoning_trace=attempt.raw_response,
            revision_count=attempt.revision_count,
            time_taken_seconds=attempt.time_taken_seconds,
            baseline_time_seconds=effective_baseline,
        )

        exec_result_visible = executor.run(
            task_id=f"{task_id}_visible",
            solution_code=attempt.solution_code,
            test_code=task["visible_test_code"],
        )
        outcome = compute_outcome_confidence(exec_result_visible)

        # Held-out split: the agent's solution is graded against a SEPARATE,
        # more thorough test suite it never had a chance to see or run
        # against. This is what `outcome` (visible) is being compared to as
        # ground truth — previously these were the same number, which
        # trivially favored 3-way fusion. Now they're genuinely independent:
        # a solution can pass the visible check and still fail here.
        exec_result_held_out = executor.run(
            task_id=f"{task_id}_held_out",
            solution_code=attempt.solution_code,
            test_code=task["held_out_test_code"],
        )
        ground_truth = compute_outcome_confidence(exec_result_held_out)

        result = fusion.process_attempt(
            task_id=task_id,
            verbalized=attempt.verbalized_confidence,
            behavioral=behavioral.normalized,
            outcome=outcome.normalized,
            ground_truth=ground_truth.normalized,
        )

        record_attempt(
            conn,
            agent_id=AGENT_ID,
            model_name=attempt.model_used,
            tier="heavy" if difficulty == "hard" else "fast",
            task_id=task_id,
            task_type=task["task_type"],
            difficulty=difficulty,
            benchmark_source=task["benchmark_source"],
            attempt_id=str(uuid.uuid4()),
            verbalized_conf=attempt.verbalized_confidence,
            behavioral_conf=behavioral.normalized,
            outcome_conf=outcome.normalized,
            fused_2way=result.fused_2way,
            fused_3way=result.fused_3way,
            brier_2way=result.brier_2way,
            brier_3way=result.brier_3way,
            succeeded=exec_result_held_out.succeeded,
        )

        print(
            f"  visible: {exec_result_visible.tests_passed}/{exec_result_visible.tests_collected} passed  "
            f"| held-out: {exec_result_held_out.tests_passed}/{exec_result_held_out.tests_collected} passed  "
            f"| verbalized={attempt.verbalized_confidence:.2f} "
            f"behavioral={behavioral.normalized:.2f} "
            f"outcome={outcome.normalized:.2f} "
            f"ground_truth={ground_truth.normalized:.2f}"
        )

        # Zero tests collected almost always means the solution failed to
        # import (syntax error, wrong function/class name, etc.) — OR that
        # the sandbox/executor itself failed to run pytest at all (missing
        # binary, launch error), in which case stdout is empty and the real
        # explanation is in stderr/container_error/exit_code instead.
        # Printing all four, not just stdout, so an empty stdout doesn't
        # get misread as "the solution was broken" when it might mean
        # "pytest never ran."
        if exec_result_visible.tests_collected == 0 or exec_result_held_out.tests_collected == 0:
            print("  [diagnostic] zero tests collected:")
            print("  --- solution code sent to sandbox ---")
            for line in attempt.solution_code.splitlines():
                print(f"    {line}")
            for label, r in (("visible", exec_result_visible), ("held-out", exec_result_held_out)):
                if r.tests_collected == 0:
                    print(f"  --- {label} run: exit_code={r.exit_code} timed_out={r.timed_out} ---")
                    print(f"    stdout: {r.stdout.strip()[:1500]!r}")
                    print(f"    stderr: {r.stderr.strip()[:1500]!r}")
                    print(f"    container_error: {r.container_error!r}")
            print()

        print(
            f"  brier_2way={result.brier_2way:.4f}  brier_3way={result.brier_3way:.4f}\n"
        )

    print("=" * 60)
    print("PHASE 0 RESULT")
    print("=" * 60)
    summary = fusion.summary()
    print(json.dumps(summary, indent=2))

    if summary["three_way_wins"]:
        print(
            "\n3-way fusion beat 2-way fusion on this run, with an independent "
            "held-out test split (outcome and ground_truth are no longer the "
            "same signal) — this is real evidence for the Praxis thesis, not "
            "just a structural artifact. Still worth more tasks over time to "
            "firm up the confidence interval, but this result means something."
        )
    else:
        print(
            "\n3-way fusion did NOT beat 2-way fusion, even with the held-out "
            "split. Worth taking seriously before proceeding to Phase 1 — this "
            "isn't just a data artifact anymore, so it may mean outcome-grounding "
            "isn't adding what the architecture doc assumed it would, at least "
            "not on this task distribution."
        )


if __name__ == "__main__":
    run()