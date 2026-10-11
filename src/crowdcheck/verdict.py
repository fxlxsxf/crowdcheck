"""One descriptive sentence about the crowd's track record.

Built only from computed values. It never labels the token or advises anything;
the forbidden-word test in tests/test_verdict.py enforces that.
"""

from __future__ import annotations

from collections.abc import Sequence

from .metrics import fmt_count, fmt_duration, ordinal
from .models import MetricName, MetricResult

CLOSING_LINE = "we didn't read the contract. we read the room."


def verdict(results: Sequence[MetricResult]) -> str:
    by = {r.name: r for r in results if r.visible}
    parts: list[str] = []

    if (r := by.get(MetricName.TRACK_RECORD)) and r.raw["prior_mints"]:
        parts.append(f"bought {fmt_count(r.raw['prior_mints'], 'token')} before and "
                     f"{r.raw['survived']} of them lasted 30 days")
    elif r:
        parts.append("has no prior DEX buys on record")
    if r := by.get(MetricName.HOLD_TIME):
        parts.append(f"held a typical position for {fmt_duration(r.raw['median_seconds'])}")
    if r := by.get(MetricName.EXIT_PERCENTILE):
        parts.append(f"sold at the {ordinal(round(r.raw['median_percentile']))} percentile of a token's range")
    if (r := by.get(MetricName.WALLET_AGE)) and not parts:
        parts.append(f"is {r.raw['share_under_7d'] * 100:.0f}% wallets less than a week old")

    if not parts:
        return "Not enough of this crowd's history is visible to describe it."
    if len(parts) == 1:
        body = parts[0]
    else:
        body = ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"This crowd {body}."
