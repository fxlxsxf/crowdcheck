from crowdcheck.metrics import overlap
from crowdcheck.models import Holding
from helpers import holders

IGNORE = frozenset({"USDC"})


def h(*mints):
    return [Holding(mint=m, amount=1.0) for m in mints]


def test_overlap_by_hand():
    holdings = {
        "w1": h("T", "X", "Y", "Z", "USDC"),
        "w2": h("X", "Y", "Z"),
        "w3": h("X", "Y"),
        "w4": [Holding("X", 0.0), Holding("Q", 1.0)],   # zero balance does not count
        "w5": None,                                     # not resolved
    }
    r = overlap(holders("w1", "w2", "w3", "w4", "w5"), holdings, exclude_mint="T", ignore_mints=IGNORE, top_k=3)
    # X: 3, Y: 3, Z: 2, Q: 1 -> top X, Y, Z; w1 and w2 hold all three
    assert [t["mint"] for t in r.raw["top"]] == ["X", "Y", "Z"]
    assert [t["holders"] for t in r.raw["top"]] == [3, 3, 2]
    assert r.raw["wallets"] == 4 and r.raw["holding_all_top"] == 2
    assert r.display == "2 of 4 of these wallets also hold the same 3 tokens"
    assert r.coverage == "4 of 5 wallets resolved"


def test_ties_break_by_mint_name():
    r = overlap(holders("a", "b"), {"a": h("B", "A"), "b": h("C")}, exclude_mint="T", ignore_mints=IGNORE, top_k=2)
    assert [t["mint"] for t in r.raw["top"]] == ["A", "B"]


def test_nothing_shared():
    r = overlap(holders("a"), {"a": h("T", "USDC")}, exclude_mint="T", ignore_mints=IGNORE, top_k=3)
    assert r.visible and r.raw["top"] == [] and r.raw["holding_all_top"] == 0


def test_no_holdings_resolved():
    assert not overlap(holders("a"), {"a": None}, exclude_mint="T", ignore_mints=IGNORE, top_k=3).visible
