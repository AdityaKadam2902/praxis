"""
calibration/outcome.py

Signal 3 of 3 — the new one, the one that doesn't exist in two-way fusion
systems, and the one this whole project's thesis rests on.

Unlike verbalized and behavioral, this signal has no model in the loop at
all. It's a direct translation of sandbox.executor.ExecutionResult into a
0.0-1.0 confidence number. That's what makes it trustworthy as "ground
truth" rather than another flavor of self-assessment.
"""

from __future__ import annotations

from dataclasses import dataclass

# Imported lazily by callers to avoid a hard dependency on docker being
# installed wherever calibration math is being unit-tested in isolation.
from sandbox.executor import ExecutionResult


@dataclass
class OutcomeConfidence:
    pass_fraction: float
    succeeded: bool
    timed_out: bool
    container_error: bool
    normalized: float  # 0.0-1.0, what fusion.py consumes


def compute_outcome_confidence(result: ExecutionResult) -> OutcomeConfidence:
    """
    Straight passthrough of the sandbox's pass_fraction as the normalized
    score, with timeouts and container errors already folded into
    pass_fraction == 0.0 by ExecutionResult itself.

    Deliberately no smoothing/optimism here — this is the one signal in the
    fusion that's allowed to be blunt, because it's the one signal that's
    actually true.
    """
    return OutcomeConfidence(
        pass_fraction=result.pass_fraction,
        succeeded=result.succeeded,
        timed_out=result.timed_out,
        container_error=bool(result.container_error),
        normalized=result.pass_fraction,
    )
