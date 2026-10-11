from datetime import timedelta

from conftest import NOW
from crowdcheck.metrics import crowd_track_record, is_survivor, prior_mints
from helpers import meta, trade


def m(first_days_ago, last_days_ago, complete=True, mint="M"):
    return meta(mint, first_trade_ts=NOW - timedelta(days=first_days_ago),
                last_trade_ts=NOW - timedelta(days=last_days_ago), history_complete=complete)


def test_survivor_rules():
    assert is_survivor(m(60, 1), now=NOW) is True            # 59 days, active
    assert is_survivor(m(31, 1), now=NOW) is True            # exactly 30 days of life
    assert is_survivor(m(30, 1), now=NOW) is False           # 29 days of life
    assert is_survivor(m(90, 8), now=NOW) is False           # long life but stale
    assert is_survivor(m(37, 7), now=NOW) is True            # exactly 7 days stale counts


def test_single_trade_mint_never_survives():
    one = meta("M", first_trade_ts=NOW - timedelta(days=2), last_trade_ts=NOW - timedelta(days=2), trade_count=1)
    assert is_survivor(one, now=NOW) is False


def test_missing_timestamps_are_undecided():
    assert is_survivor(meta("M"), now=NOW) is None
    assert is_survivor(meta("M", last_trade_ts=NOW), now=NOW) is None


def test_incomplete_history_is_undecided_unless_already_long_enough():
    assert is_survivor(m(10, 1, complete=False), now=NOW) is None
    assert is_survivor(m(40, 1, complete=False), now=NOW) is True


def test_prior_mints_orders_by_breadth_excludes_target_and_caps():
    trades = {
        "w1": [trade("A", "buy", 0, 1), trade("B", "buy", 0, 1), trade("T", "buy", 0, 1)],
        "w2": [trade("A", "buy", 0, 1), trade("C", "sell", 0, 1)],   # a sell alone is not "held before"
        "w3": None,                                                   # fetch failed
    }
    assert prior_mints(trades, exclude_mint="T", cap=10) == (["A", "B"], False)
    assert prior_mints(trades, exclude_mint="T", cap=1) == (["A"], True)


def test_track_record_by_hand():
    mints = ["A", "B", "C", "D"]
    metas = {"A": m(60, 1, mint="A"), "B": m(5, 1, mint="B"), "C": m(100, 50, mint="C"), "D": None}
    r = crowd_track_record(mints, metas, cap_hit=False, now=NOW, wallets_resolved=3, wallets_total=4)
    assert r.raw == {"prior_mints": 4, "resolved": 3, "survived": 1, "survival_rate": 1 / 3, "cap_hit": False}
    assert r.display == "4 tokens held by this crowd before, 1 of them survived (3 of 4 lifespans resolved)"


def test_cap_is_reported():
    r = crowd_track_record(["A"], {"A": m(60, 1, mint="A")}, cap_hit=True, now=NOW,
                           wallets_resolved=1, wallets_total=1)
    assert r.raw["cap_hit"] and "capped" in r.display


def test_crowd_with_zero_prior_trades():
    r = crowd_track_record([], {}, cap_hit=False, now=NOW, wallets_resolved=5, wallets_total=5)
    assert r.visible and r.raw["prior_mints"] == 0 and r.raw["survival_rate"] is None
    assert r.display.startswith("0 tokens")


def test_no_wallets_resolved_is_not_visible():
    r = crowd_track_record([], {}, cap_hit=False, now=NOW, wallets_resolved=0, wallets_total=5)
    assert not r.visible


def test_no_lifespan_resolved_is_not_visible():
    r = crowd_track_record(["A"], {"A": None}, cap_hit=False, now=NOW, wallets_resolved=1, wallets_total=1)
    assert not r.visible and r.reason == "no prior mint lifespan resolved"
