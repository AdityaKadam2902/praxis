"""
calibration/fusion.py

This is the file Phase 0 exists to validate. It fuses the three signals
into a single predicted-confidence number, using two competing models:

  - fused_2way = f(verbalized, behavioral)              [what Nexus did]
  - fused_3way = f(verbalized, behavioral, outcome)      [the Praxis thesis]

...and scores both against ground truth via Brier score. Lower is better.
Whichever wins on the benchmark set (benchmark/run_benchmark.py) determines
whether Phase 1 proceeds with 3-way fusion as designed, or whether the
architecture doc needs revisiting.

Model: simple online logistic regression per fusion type, updated after
every graded attempt. Deliberately not a neural net or anything fancy —
with ~20-30 benchmark tasks in Phase 0, a 2-3 parameter logistic model is
the right amount of machinery. Upgrade only once there's enough logged
data (Phase 2+) to justify more parameters without overfitting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _sigmoid(x: float) -> float:
    # Numerically stable sigmoid
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass
class OnlineLogisticFusion:
    """
    Minimal online logistic regression: predicted = sigmoid(w . x + b).
    Updated one example at a time via gradient descent (SGD), which is all
    Phase 0's task volume needs and keeps this dependency-free (no sklearn
    required just to run the core experiment).
    """

    n_features: int
    learning_rate: float = 0.1
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    n_updates: int = 0

    def __post_init__(self) -> None:
        if not self.weights:
            # Start at equal weighting (~1/n each) rather than zero, so the
            # model produces sane predictions before any training examples
            # have been seen.
            self.weights = [1.0 / self.n_features] * self.n_features

    def predict(self, features: list[float]) -> float:
        z = sum(w * x for w, x in zip(self.weights, features)) + self.bias
        return _sigmoid(z)

    def update(self, features: list[float], actual_outcome: float) -> float:
        """
        One SGD step against the true observed outcome (0.0-1.0, typically
        the sandbox pass_fraction). Returns the pre-update prediction so
        callers can log the Brier score for that example.
        """
        prediction = self.predict(features)
        error = prediction - actual_outcome  # gradient of squared-error-ish loss

        for i in range(self.n_features):
            self.weights[i] -= self.learning_rate * error * features[i]
        self.bias -= self.learning_rate * error

        self.n_updates += 1
        return prediction


@dataclass
class FusionResult:
    fused_2way: float
    fused_3way: float
    brier_2way: float
    brier_3way: float


class CalibrationFusionEngine:
    """
    Owns both the 2-way and 3-way online models and runs them side by side
    on every attempt, so Phase 0 produces a direct, apples-to-apples
    comparison rather than two separately-run experiments.
    """

    def __init__(self) -> None:
        self.model_2way = OnlineLogisticFusion(n_features=2)  # [verbalized, behavioral]
        self.model_3way = OnlineLogisticFusion(n_features=3)  # [verbalized, behavioral, outcome]
        self.history: list[dict] = []

    def process_attempt(
        self,
        task_id: str,
        verbalized: float,
        behavioral: float,
        outcome: float,
        ground_truth: float,
    ) -> FusionResult:
        """
        ground_truth is the *held-out* correctness signal — in Phase 0 this
        is the same sandbox pass_fraction as `outcome`, computed against a
        test set the agent never saw, to keep the 3-way model honest (it
        isn't allowed to just memorize `outcome` as a shortcut to a perfect
        score — see note below).
        """
        features_2way = [verbalized, behavioral]
        features_3way = [verbalized, behavioral, outcome]

        pred_2way = self.model_2way.update(features_2way, ground_truth)
        pred_3way = self.model_3way.update(features_3way, ground_truth)

        brier_2way = (pred_2way - ground_truth) ** 2
        brier_3way = (pred_3way - ground_truth) ** 2

        result = FusionResult(
            fused_2way=pred_2way,
            fused_3way=pred_3way,
            brier_2way=brier_2way,
            brier_3way=brier_3way,
        )

        self.history.append(
            {
                "task_id": task_id,
                "verbalized": verbalized,
                "behavioral": behavioral,
                "outcome": outcome,
                "ground_truth": ground_truth,
                **result.__dict__,
            }
        )
        return result

    def summary(self) -> dict:
        """Aggregate Brier scores across all attempts so far — the Phase 0 headline number."""
        if not self.history:
            return {"n": 0, "mean_brier_2way": None, "mean_brier_3way": None}

        n = len(self.history)
        mean_2way = sum(h["brier_2way"] for h in self.history) / n
        mean_3way = sum(h["brier_3way"] for h in self.history) / n

        return {
            "n": n,
            "mean_brier_2way": round(mean_2way, 4),
            "mean_brier_3way": round(mean_3way, 4),
            "improvement": round(mean_2way - mean_3way, 4),
            "three_way_wins": mean_3way < mean_2way,
        }


# NOTE ON THE "OUTCOME == GROUND TRUTH" OVERLAP — RESOLVED:
#
# Earlier Phase 0 runs used sandbox pass_fraction as both the input feature
# (outcome) and the training target (ground_truth), which trivially favored
# 3-way fusion — the model could partially learn to just copy that one
# feature. run_benchmark.py now splits each task's tests into a visible
# subset (what `outcome` is computed from) and a held-out subset the agent
# never saw (what `ground_truth` is scored against) — see
# benchmark/tasks/seed_tasks.json's visible_test_code / held_out_test_code
# fields. outcome and ground_truth are now genuinely independent signals,
# so a 3-way win is real evidence, not a structural artifact.