"""History score: a weighted sum of six sub-scores, each a straight line.

The mappings below are deliberately simple so every point can be traced back by
hand. All anchors and weights come from config.py and are arbitrary.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from . import config
from .models import Contribution, MetricName, MetricResult, ScoreResult


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _linear(x: float, zero: float, full: float) -> float:
    return _clamp((x - zero) / (full - zero))


def metric_subscore(result: MetricResult) -> float | None:
    """0..1 where 1 means a long, durable visible history. None if not visible."""
    if not result.visible:
        return None
    raw = result.raw
    match result.name:
        case MetricName.TRACK_RECORD:
            # No prior tokens at all is a history of nothing: scores 0.
            rate = raw.get("survival_rate")
            return 0.0 if rate is None else _linear(rate, 0.0, config.SURVIVAL_RATE_FULL)
        case MetricName.WALLET_AGE:
            return _clamp(1 - (raw["share_under_24h"] + raw["share_under_7d"]) / 2)
        case MetricName.DEPLOYER:
            return _linear(raw["median_outcome_pct"], config.DEPLOYER_OUTCOME_ZERO, config.DEPLOYER_OUTCOME_FULL)
        case MetricName.OVERLAP:
            return _clamp(1 - raw["share_holding_all_top"])
        case MetricName.HOLD_TIME:
            median = max(raw["median_seconds"], 1.0)
            hold = _linear(math.log10(median), math.log10(config.HOLD_TIME_ZERO_SECONDS),
                           math.log10(config.HOLD_TIME_FULL_SECONDS))
            return (hold + (1 - raw["share_under_fast"])) / 2
        case MetricName.EXIT_PERCENTILE:
            return _clamp(1 - raw["median_percentile"] / 100)
    return None


def score(results: Sequence[MetricResult], weights: dict[str, int] | None = None) -> ScoreResult:
    weights = weights or config.WEIGHTS
    contributions: dict[MetricName, Contribution] = {}
    for r in results:
        w = weights[r.name.value]
        sub = metric_subscore(r)
        contributions[r.name] = Contribution(weight=w, subscore=sub, points=None if sub is None else w * sub)

    hidden = sum(1 for c in contributions.values() if c.subscore is None)
    visible_weight = sum(c.weight for c in contributions.values() if c.subscore is not None)
    too_thin = hidden > config.MAX_NOT_VISIBLE_FOR_SCORE or visible_weight == 0
    total = None
    if not too_thin:
        points = sum(c.points for c in contributions.values() if c.points is not None)
        # Rescale so a missing metric neither adds nor subtracts: total is out of the visible weight.
        total = points * 100 / visible_weight
    return ScoreResult(total=total, contributions=contributions, visible_weight=visible_weight, too_thin=too_thin)
