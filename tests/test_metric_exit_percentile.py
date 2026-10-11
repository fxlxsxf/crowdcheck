from crowdcheck.metrics import crowd_exit_percentile, exit_percentile, ordinal
from crowdcheck.models import Position
from helpers import closed_position, meta

RANGE = meta("M", price_low=0.5, price_high=4.0, quote="SOL")


def test_single_exit_by_hand():
    # (2.0 - 0.5) / (4.0 - 0.5) * 100 = 42.857...
    assert round(exit_percentile(closed_position(10, sell_price=2.0), RANGE), 3) == 42.857


def test_clamped_to_range():
    assert exit_percentile(closed_position(10, sell_price=9.0), RANGE) == 100
    assert exit_percentile(closed_position(10, sell_price=0.1), RANGE) == 0


def test_unusable_inputs():
    assert exit_percentile(closed_position(10), RANGE) is None                                  # no sell price
    assert exit_percentile(closed_position(10, sell_price=1.0, quote="USD"), RANGE) is None     # quote mismatch
    flat = meta("M", price_low=1.0, price_high=1.0)                                             # single-trade mint
    assert exit_percentile(closed_position(10, sell_price=1.0), flat) is None
    open_p = Position("w", "M", None, None, 1, 0, 1.0, "SOL", closed=False)
    assert exit_percentile(open_p, RANGE) is None


def test_crowd_median_by_hand():
    metas = {"A": RANGE, "B": meta("B", price_low=0.25, price_high=1.0, quote="SOL"), "D": None}
    r = crowd_exit_percentile({
        "w1": [closed_position(30, mint="A", sell_price=2.0), closed_position(100, mint="B", sell_price=0.75)],
        "w2": [closed_position(1200, mint="A", sell_price=3.0)],
        "w3": [closed_position(45, mint="D", sell_price=1.5)],
    }, metas)
    # 42.86, 66.67, 71.43 -> median 66.67
    assert round(r.raw["median_percentile"], 2) == 66.67
    assert r.raw["exits"] == 3 and r.coverage == "3 of 4 exits priced"
    assert r.display == "this crowd's median exit sits at the 67th percentile of a token's range"


def test_not_visible_cases():
    assert crowd_exit_percentile({"w": []}, {}).reason == "no completed prior positions"
    assert crowd_exit_percentile({"w": [closed_position(5, mint="A")]}, {"A": RANGE}).reason == "no priced exits"


def test_ordinal():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 81, 100)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "81st", "100th"]
