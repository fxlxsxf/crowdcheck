from datetime import timedelta

from conftest import NOW
from crowdcheck.metrics import wallet_age
from helpers import holders


def test_shares_by_hand():
    first = {
        "a": NOW - timedelta(hours=1),    # today
        "b": NOW - timedelta(hours=23),   # today
        "c": NOW - timedelta(days=3),     # this week
        "d": NOW - timedelta(days=30),    # old
        "e": None,                        # not resolved, excluded from the denominator
    }
    r = wallet_age(holders("a", "b", "c", "d", "e"), first, now=NOW)
    assert r.visible
    assert r.raw["resolved"] == 4
    assert r.raw["under_24h"] == 2 and r.raw["share_under_24h"] == 0.5
    assert r.raw["under_7d"] == 3 and r.raw["share_under_7d"] == 0.75
    assert r.display == "50% of these wallets were created today, 75% this week"
    assert r.coverage == "4 of 5 wallets resolved"


def test_boundary_exactly_24h_is_not_today():
    r = wallet_age(holders("a"), {"a": NOW - timedelta(hours=24)}, now=NOW)
    assert r.raw["under_24h"] == 0 and r.raw["under_7d"] == 1


def test_nothing_resolved_is_not_visible():
    r = wallet_age(holders("a", "b"), {}, now=NOW)
    assert not r.visible and r.display == "not visible" and r.reason


def test_empty_holder_list():
    assert not wallet_age([], {}, now=NOW).visible
