from crowdcheck.metrics import fmt_duration, hold_time
from helpers import closed_position
from crowdcheck.models import Position


def test_median_and_fast_share_by_hand():
    r = hold_time({
        "w1": [closed_position(30), closed_position(100)],
        "w2": [closed_position(1200)],
        "w3": [closed_position(45)],
    })
    # durations 30, 45, 100, 1200 -> median (45 + 100) / 2 = 72.5; under 60s: 30 and 45
    assert r.raw["median_seconds"] == 72.5
    assert r.raw["under_fast"] == 2 and r.raw["share_under_fast"] == 0.5
    assert r.display == "median prior position lasted 72 seconds, 50% closed under 60 seconds"


def test_open_positions_are_ignored():
    open_p = Position(wallet="w", mint="M", first_buy_ts=None, last_sell_ts=None, bought=1, sold=0,
                      avg_sell_price=None, quote=None, closed=False)
    r = hold_time({"w": [open_p, closed_position(94)]})
    assert r.raw["positions"] == 1 and r.raw["median_seconds"] == 94


def test_wallet_with_zero_prior_trades_is_not_visible():
    r = hold_time({"w": []})
    assert not r.visible and r.reason == "no completed prior positions"


def test_exactly_60_seconds_is_not_fast():
    assert hold_time({"w": [closed_position(60)]}).raw["under_fast"] == 0


def test_fmt_duration():
    assert fmt_duration(94) == "94 seconds"
    assert fmt_duration(600) == "10 minutes"
    assert fmt_duration(3 * 3600) == "3.0 hours"
    assert fmt_duration(3 * 86400) == "3.0 days"
