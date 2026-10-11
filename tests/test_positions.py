from crowdcheck.metrics import build_positions
from helpers import T0, at, trade


def test_round_trip_is_closed_with_vwap_exit():
    ps = build_positions([
        trade("M", "buy", 0, 100, 1.0),
        trade("M", "sell", 10, 60, 2.0),
        trade("M", "sell", 40, 40, 3.0),
    ])
    assert len(ps) == 1
    p = ps[0]
    assert p.closed and p.duration_seconds == 40
    # (60*2 + 40*3) / 100 = 2.4, written out by hand
    assert p.avg_sell_price == 2.4


def test_partial_exit_below_threshold_is_open():
    (p,) = build_positions([trade("M", "buy", 0, 100), trade("M", "sell", 10, 94)])
    assert not p.closed and p.duration_seconds is None


def test_exit_at_threshold_is_closed():
    (p,) = build_positions([trade("M", "buy", 0, 100), trade("M", "sell", 10, 95)])
    assert p.closed


def test_sell_without_buy_never_closes():
    (p,) = build_positions([trade("M", "sell", 10, 50, 1.0)])
    assert not p.closed and p.bought == 0


def test_sell_before_buy_does_not_close():
    (p,) = build_positions([trade("M", "sell", 0, 100), trade("M", "buy", 10, 100)])
    assert not p.closed


def test_excluded_mint_and_empty_input():
    assert build_positions([trade("T", "buy", 0, 1)], exclude_mint="T") == []
    assert build_positions([]) == []


def test_mixed_quotes_give_no_exit_price():
    (p,) = build_positions([trade("M", "buy", 0, 10, 1.0),
                            trade("M", "sell", 5, 5, 2.0, quote="SOL"),
                            trade("M", "sell", 6, 5, 2.0, quote="USD")])
    assert p.closed and p.avg_sell_price is None


def test_first_buy_and_last_sell_bracket_the_position():
    (p,) = build_positions([trade("M", "buy", 5, 10), trade("M", "buy", 0, 10),
                            trade("M", "sell", 30, 10), trade("M", "sell", 90, 10)])
    assert p.first_buy_ts == T0 and p.last_sell_ts == at(90)
