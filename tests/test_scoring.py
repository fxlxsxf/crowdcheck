import math

import pytest

from crowdcheck import config
from crowdcheck.metrics import not_visible
from crowdcheck.models import MetricName, MetricResult
from crowdcheck.scoring import metric_subscore, score


def ok(name, **raw):
    return MetricResult(name=name, status="ok", display="", raw=raw)


FULL = [
    ok(MetricName.TRACK_RECORD, survival_rate=1 / 3),
    ok(MetricName.WALLET_AGE, share_under_24h=0.5, share_under_7d=0.75),
    ok(MetricName.DEPLOYER, median_outcome_pct=-96.5),
    ok(MetricName.OVERLAP, share_holding_all_top=0.5),
    ok(MetricName.HOLD_TIME, median_seconds=72.5, share_under_fast=0.5),
    ok(MetricName.EXIT_PERCENTILE, median_percentile=200 / 3),
]


def test_subscores_by_hand():
    s = [metric_subscore(r) for r in FULL]
    assert s[0] == 1.0                          # 0.333 survival is above the 0.25 anchor
    assert s[1] == 0.375                        # 1 - (0.5 + 0.75) / 2
    assert s[2] == pytest.approx(0.035)         # (-96.5 + 100) / 100
    assert s[3] == 0.5
    hold = (math.log10(72.5) - math.log10(60)) / (math.log10(7 * 86400) - math.log10(60))
    assert s[4] == pytest.approx((hold + 0.5) / 2)
    assert s[5] == pytest.approx(1 / 3)


def test_total_is_sum_of_points():
    result = score(FULL)
    pts = sum(c.points for c in result.contributions.values())
    assert result.total == pytest.approx(pts)
    assert result.visible_weight == 100 and not result.too_thin
    assert result.contributions[MetricName.TRACK_RECORD].points == 25


def test_weights_sum_to_100():
    assert sum(config.WEIGHTS.values()) == 100


def test_hidden_metric_rescales_over_visible_weight():
    rs = [not_visible(MetricName.DEPLOYER, "x") if r.name == MetricName.DEPLOYER else r for r in FULL]
    result = score(rs)
    pts = sum(c.points for c in result.contributions.values() if c.points is not None)
    assert result.visible_weight == 85
    assert result.total == pytest.approx(pts * 100 / 85)


def test_three_hidden_metrics_refuse_a_score():
    rs = [not_visible(r.name, "x") if i < 3 else r for i, r in enumerate(FULL)]
    result = score(rs)
    assert result.too_thin and result.total is None


def test_zero_prior_tokens_scores_zero():
    assert metric_subscore(ok(MetricName.TRACK_RECORD, survival_rate=None)) == 0.0
