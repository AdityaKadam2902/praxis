"""
calibration/verbalized.py

Signal 1 of 3: what the agent SAYS about its own confidence.

Weakest signal on its own (models are notoriously overconfident), but cheap
to get and still informative once fused with the other two — especially as
a way to detect *systematic* overconfidence patterns per agent per task-type
over time (that pattern-detection is the real payoff, in Phase 1+).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


CONFIDENCE_PROMPT_SUFFIX = """
After writing your solution, on a new final line, output ONLY:
CONFIDENCE: <a number between 0 and 100 representing how confident you are
that your solution is fully correct>
"""

_CONFIDENCE_RE = re.compile(r"CONFIDENCE:\s*(\d{1,3})", re.IGNORECASE)


@dataclass
class VerbalizedConfidence:
    raw_score_0_100: int
    normalized: float  # 0.0-1.0, what fusion.py consumes
    parse_succeeded: bool


def extract_verbalized_confidence(agent_response_text: str) -> VerbalizedConfidence:
    """
    Pull the agent's self-reported confidence out of its raw response.
    If the agent didn't follow the format (common with smaller local models),
    fail closed to a neutral 50% rather than silently assuming high confidence —
    an agent that doesn't even report confidence shouldn't be treated as if it
    were confident.
    """
    match = _CONFIDENCE_RE.search(agent_response_text)
    if not match:
        return VerbalizedConfidence(raw_score_0_100=50, normalized=0.5, parse_succeeded=False)

    raw = max(0, min(100, int(match.group(1))))
    return VerbalizedConfidence(
        raw_score_0_100=raw,
        normalized=raw / 100.0,
        parse_succeeded=True,
    )


def strip_confidence_line(agent_response_text: str) -> str:
    """Remove the CONFIDENCE line before treating the rest as the actual solution."""
    return _CONFIDENCE_RE.sub("", agent_response_text).strip()
