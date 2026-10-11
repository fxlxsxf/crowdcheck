from datetime import timedelta

from conftest import NOW
from crowdcheck.metrics import deployer_history, lifespan_days, mint_outcome_pct
from crowdcheck.models import FundingGraph
from helpers import meta


def graph(mints, wallets=("c", "f"), truncated=False):
    return FundingGraph(creator="c", funder="f", wallets=list(wallets), linked_mints=list(mints), truncated=truncated)


def test_outcome_and_lifespan():
    assert mint_outcome_pct(meta(first_price=2.0, last_price=0.1)) == -95.0
    assert mint_outcome_pct(meta(first_price=1.0, last_price=1.5)) == 50.0
    assert mint_outcome_pct(meta(first_price=0.0, last_price=1.0)) is None
    assert mint_outcome_pct(meta(last_price=1.0)) is None
    assert lifespan_days(meta(first_trade_ts=NOW - timedelta(days=40), last_trade_ts=NOW)) == 40


def test_deployer_by_hand():
    metas = {
        "P1": meta("P1", first_price=1.0, last_price=0.02, first_trade_ts=NOW - timedelta(days=10), last_trade_ts=NOW),
        "P2": meta("P2", first_price=2.0, last_price=0.1, first_trade_ts=NOW - timedelta(days=40), last_trade_ts=NOW),
        "P3": meta("P3", first_trade_ts=NOW - timedelta(days=5), last_trade_ts=NOW),   # no prices
        "P4": None,                                                                     # unresolved
    }
    r = deployer_history(graph(["P1", "P2", "P3", "P4"]), metas)
    # outcomes -98 and -95 -> median -96.5; longest lifespan 40 days
    assert r.raw["median_outcome_pct"] == -96.5
    assert r.raw["longest_survivor_days"] == 40
    assert r.raw["linked_mints"] == 4 and r.raw["priced"] == 2
    assert r.display == "this deployer is linked to 4 prior mints, median outcome -96%, longest survivor 40 days"


def test_no_graph_and_empty_graph():
    assert deployer_history(None, {}).reason == "creator or funding graph not resolved"
    r = deployer_history(graph([]), {})
    assert not r.visible and r.reason == "no linked history visible"


def test_mint_with_single_trade_has_zero_change():
    one = meta("P", first_price=1.0, last_price=1.0, first_trade_ts=NOW, last_trade_ts=NOW)
    r = deployer_history(graph(["P"]), {"P": one})
    assert r.raw["median_outcome_pct"] == 0 and r.raw["longest_survivor_days"] == 0


def test_unpriced_links_are_not_visible():
    r = deployer_history(graph(["P"]), {"P": meta("P")})
    assert not r.visible and r.reason == "linked mints have no price history"
