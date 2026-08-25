"""
calibration/behavioral.py

Signal 2 of 3: what the agent's PROCESS implies about its confidence,
independent of what it explicitly claims. Models that are actually unsure
tend to hedge, revise more, and take longer relative to task-type baselines
— this signal catches that even when the verbalized number says "95%".

Phase 0 keeps this deliberately simple (word-list + counters). Swap for a
learned model once there's enough logged data to train one — that's a
Phase 2+ upgrade, not a Phase 0 blocker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEDGING_PATTERNS = [
    r"\bi think\b",
    r"\bmight\b",
    r"\bprobably\b",
    r"\bnot (entirely |fully |completely )?sure\b",
    r"\bcould be wrong\b",
    r"\bpossibly\b",
    r"\bi believe\b",
    r"\bshould work\b",  # weaker than "this works"
    r"\btry(ing)? to\b",
    r"\bmay not\b",
]
_HEDGE_RE = re.compile("|".join(HEDGING_PATTERNS), re.IGNORECASE)


@dataclass
class BehavioralConfidence:
    revision_count: int
    hedge_count: int
    time_taken_seconds: float
    baseline_time_seconds: float
    normalized: float  # 0.0-1.0, what fusion.py consumes


def compute_behavioral_confidence(
    reasoning_trace: str,
    revision_count: int,
    time_taken_seconds: float,
    baseline_time_seconds: float,
) -> BehavioralConfidence:
    """
    Combine three weak process signals into one behavioral confidence score.

    - More hedging language -> lower confidence
    - More revisions before settling on an answer -> lower confidence
    - Taking much longer than the task-type's historical baseline -> lower
      confidence (struggling), taking much less -> ambiguous (could be
      genuine mastery OR skipping steps — Phase 0 treats it neutrally
      rather than guessing which)

    All three are weak signals individually; that's expected and fine —
    this is one of three inputs to fusion.py, not a standalone verdict.
    """
    hedge_count = len(_HEDGE_RE.findall(reasoning_trace))

    # Hedging: 0 hedges -> 1.0, scales down, floors at 0.3 (never fully zero
    # out on language alone — this is a weak signal, not a disqualifier).
    hedge_score = max(0.3, 1.0 - 0.15 * hedge_count)

    # Revisions: 0-1 revisions is normal for a working solution; each
    # additional revision beyond that nudges confidence down.
    revision_score = max(0.3, 1.0 - 0.1 * max(0, revision_count - 1))

    # Time ratio: only penalize meaningfully *slower* than baseline.
    # Faster-than-baseline is treated as neutral (1.0) rather than rewarded,
    # since speed alone isn't evidence of correctness.
    if baseline_time_seconds > 0:
        ratio = time_taken_seconds / baseline_time_seconds
        time_score = 1.0 if ratio <= 1.2 else max(0.3, 1.0 - 0.2 * (ratio - 1.2))
    else:
        time_score = 1.0

    normalized = (hedge_score + revision_score + time_score) / 3.0

    return BehavioralConfidence(
        revision_count=revision_count,
        hedge_count=hedge_count,
        time_taken_seconds=time_taken_seconds,
        baseline_time_seconds=baseline_time_seconds,
        normalized=round(normalized, 4),
    )
