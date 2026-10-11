import re

from crowdcheck.metrics import not_visible
from crowdcheck.models import MetricName, MetricResult
from crowdcheck.verdict import CLOSING_LINE, verdict

FORBIDDEN = re.compile(r"\b(buy|sell|hold|bullish|bearish|safe|scam|recommend\w*|should|avoid)\b", re.I)


def ok(name, **raw):
    return MetricResult(name=name, status="ok", display="", raw=raw)


def test_verdict_by_hand():
    v = verdict([
        ok(MetricName.TRACK_RECORD, prior_mints=412, survived=3),
        ok(MetricName.HOLD_TIME, median_seconds=94),
        ok(MetricName.EXIT_PERCENTILE, median_percentile=81),
    ])
    assert v == ("This crowd bought 412 tokens before and 3 of them lasted 30 days, held a typical position "
                 "for 94 seconds and sold at the 81st percentile of a token's range.")


def test_verdict_with_nothing_visible():
    v = verdict([not_visible(n, "x") for n in MetricName])
    assert v == "Not enough of this crowd's history is visible to describe it."


def test_no_advice_words_in_any_output_line():
    # "bought"/"sold"/"held" are past-tense descriptions; the bare advice words must never appear.
    samples = [verdict([ok(MetricName.TRACK_RECORD, prior_mints=n, survived=0),
                        ok(MetricName.HOLD_TIME, median_seconds=5)]) for n in (0, 1, 50)]
    samples.append(verdict([ok(MetricName.WALLET_AGE, share_under_7d=0.9)]))
    for text in samples + [CLOSING_LINE]:
        assert not FORBIDDEN.search(text), text
