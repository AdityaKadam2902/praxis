"""
orchestrator/routing.py

Trust-based router — build spec section 6. Replaces Phase 0's hardcoded
difficulty-only tier selection with one that queries real calibration
history (mean brier_3way) per (task_type, difficulty, tier) from Kuzu.

Cold-start fallback: if fewer than MIN_ATTEMPTS_FOR_ROUTING attempts
exist for either tier on this exact (task_type, difficulty) combination,
falls back to Phase 0's difficulty-only default (heavy for "hard", fast
otherwise) rather than routing on a noisy small sample.
MIN_ATTEMPTS_FOR_ROUTING is a starting guess, not a tuned value — the
build spec explicitly deferred picking a real number until actual data
shows how noisy small samples look in practice.
"""

from __future__ import annotations

from pathlib import Path

import kuzu

from providers.base import Provider
from graph.schema import tier_history_for_routing

# Same path-resolution approach as benchmark/run_benchmark.py's
# KUZU_DB_PATH — computed relative to this file's location, not the
# caller's cwd, so it works the same regardless of where pipeline.py is
# invoked from.
_KUZU_DB_PATH = str(Path(__file__).resolve().parent.parent / "graph" / "kuzu_db")

MIN_ATTEMPTS_FOR_ROUTING = 3


def select_model_for_task(provider: Provider, task_type: str, difficulty: str) -> str:
    history = _query_tier_history(task_type, difficulty)

    fast_n = history.get("fast", {}).get("n", 0)
    heavy_n = history.get("heavy", {}).get("n", 0)

    if fast_n < MIN_ATTEMPTS_FOR_ROUTING and heavy_n < MIN_ATTEMPTS_FOR_ROUTING:
        print(
            f"[routing] cold start for (task_type={task_type}, difficulty={difficulty}) "
            f"— fast_n={fast_n} heavy_n={heavy_n}, using difficulty-only default"
        )
        return provider.heavy_model_name() if difficulty == "hard" else provider.fast_model_name()

    fast_brier = history.get("fast", {}).get("avg_brier", float("inf"))
    heavy_brier = history.get("heavy", {}).get("avg_brier", float("inf"))
    chosen_tier = "fast" if fast_brier <= heavy_brier else "heavy"

    print(
        f"[routing] (task_type={task_type}, difficulty={difficulty}): "
        f"fast_brier={fast_brier:.4f} (n={fast_n}) vs heavy_brier={heavy_brier:.4f} (n={heavy_n}) "
        f"-> chose {chosen_tier}"
    )
    return provider.fast_model_name() if chosen_tier == "fast" else provider.heavy_model_name()


def _query_tier_history(task_type: str, difficulty: str) -> dict:
    try:
        db = kuzu.Database(_KUZU_DB_PATH)
        conn = kuzu.Connection(db)
        return tier_history_for_routing(conn, task_type, difficulty)
    except Exception as exc:  # noqa: BLE001
        # Kuzu DB not created yet, or any query failure — fail closed to
        # "no history" rather than crashing the pipeline. Same fail-closed
        # precedent as calibration/verbalized.py and agents/pm.py.
        print(f"[routing] warning: could not query Kuzu history ({exc}), treating as cold start")
        return {}