"""The six metrics, as pure functions.

No I/O happens here. Every function takes already-fetched data plus an explicit
`now`, and returns a MetricResult whose numbers are computed only from that
data. When something cannot be resolved the result is "not visible" with a short
reason, never an estimate.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from . import config
from .models import FundingGraph, Holder, Holding, MetricName, MetricResult, MintMeta, Position, Trade

# --- shared helpers --------------------------------------------------------------


def median_or_none(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def not_visible(name: MetricName, reason: str, coverage: str | None = None) -> MetricResult:
    return MetricResult(name=name, status="not_visible", display="not visible", reason=reason, coverage=coverage)


def pct(part: int | float, whole: int | float) -> float:
    return 100.0 * part / whole if whole else 0.0


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def fmt_duration(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:.0f} seconds"
    if seconds < 2 * 3600:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def fmt_count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def build_positions(trades: Sequence[Trade], *, closed_fraction: float = config.POSITION_CLOSED_FRACTION,
                    exclude_mint: str | None = None) -> list[Position]:
    """Group one wallet's trades by mint into round trips.

    A position is closed when the tokens sold cover `closed_fraction` of the
    tokens bought and the last sell comes after the first buy. Tokens that
    arrived by transfer (sells with no buys) never form a closed position.
    """
    by_key: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for t in trades:
        if t.mint == exclude_mint:
            continue
        by_key[(t.wallet, t.mint)].append(t)

    positions: list[Position] = []
    for (wallet, mint), group in sorted(by_key.items()):
        buys = [t for t in group if t.side == "buy"]
        sells = [t for t in group if t.side == "sell"]
        bought = sum(t.token_amount for t in buys)
        sold = sum(t.token_amount for t in sells)
        buy_ts = [t.ts for t in buys if t.ts]
        sell_ts = [t.ts for t in sells if t.ts]
        first_buy = min(buy_ts) if buy_ts else None
        last_sell = max(sell_ts) if sell_ts else None

        priced = [t for t in sells if t.price is not None and t.token_amount > 0]
        quotes = {t.quote for t in priced}
        avg_sell = None
        if priced and len(quotes) == 1:
            volume = sum(t.token_amount for t in priced)
            avg_sell = sum(t.price * t.token_amount for t in priced) / volume  # type: ignore[operator]

        closed = (bought > 0 and sold >= closed_fraction * bought
                  and first_buy is not None and last_sell is not None and last_sell >= first_buy)
        positions.append(Position(wallet=wallet, mint=mint, first_buy_ts=first_buy, last_sell_ts=last_sell,
                                  bought=bought, sold=sold, avg_sell_price=avg_sell,
                                  quote=quotes.pop() if len(quotes) == 1 else None, closed=closed))
    return positions


def _coverage(resolved: int, total: int, noun: str = "wallets") -> str:
    return f"{resolved} of {total} {noun} resolved"


# --- 1. crowd track record ---------------------------------------------------------


def prior_mints(trades_by_wallet: Mapping[str, Sequence[Trade] | None], *, exclude_mint: str,
                cap: int = config.PRIOR_MINT_CAP) -> tuple[list[str], bool]:
    """Distinct mints the crowd bought, most widely bought first. Returns (mints, cap_hit)."""
    buyers: Counter[str] = Counter()
    for trades in trades_by_wallet.values():
        for mint in {t.mint for t in trades or () if t.side == "buy" and t.mint != exclude_mint}:
            buyers[mint] += 1
    ordered = sorted(buyers, key=lambda m: (-buyers[m], m))
    return ordered[:cap], len(ordered) > cap


def is_survivor(meta: MintMeta, *, now: datetime, min_lifespan: timedelta = config.SURVIVOR_MIN_LIFESPAN,
                max_staleness: timedelta = config.SURVIVOR_MAX_STALENESS) -> bool | None:
    """True/False when decidable from the data, None when it is not."""
    first, last = meta.first_trade_ts, meta.last_trade_ts
    if last is None:
        return None
    if now - last > max_staleness:
        return False
    if first is None:
        return None
    lifespan = last - first
    if lifespan >= min_lifespan:
        return True
    # With incomplete history the real lifespan is at least `lifespan`, maybe longer.
    return False if meta.history_complete else None


def crowd_track_record(mints: Sequence[str], mint_meta: Mapping[str, MintMeta | None], *, cap_hit: bool,
                       now: datetime, wallets_resolved: int, wallets_total: int) -> MetricResult:
    name = MetricName.TRACK_RECORD
    coverage = _coverage(wallets_resolved, wallets_total)
    if wallets_resolved == 0:
        return not_visible(name, "no wallet trade history returned", coverage)

    outcomes = {m: is_survivor(meta, now=now) for m in mints if (meta := mint_meta.get(m)) is not None}
    decided = {m: s for m, s in outcomes.items() if s is not None}
    survived = sum(1 for s in decided.values() if s)
    if mints and not decided:
        return not_visible(name, "no prior mint lifespan resolved", coverage)

    display = f"{fmt_count(len(mints), 'token')} held by this crowd before, {survived} of them survived"
    if len(decided) < len(mints):
        display += f" ({len(decided)} of {len(mints)} lifespans resolved)"
    if cap_hit:
        display += f" (lookback capped at {len(mints)} mints)"
    return MetricResult(name=name, status="ok", display=display, coverage=coverage, raw={
        "prior_mints": len(mints), "resolved": len(decided), "survived": survived,
        "survival_rate": survived / len(decided) if decided else None, "cap_hit": cap_hit,
    })


# --- 2. wallet age -------------------------------------------------------------------


def wallet_age(holders: Sequence[Holder], first_activity: Mapping[str, datetime | None], *,
               now: datetime) -> MetricResult:
    name = MetricName.WALLET_AGE
    ages = [now - ts for h in holders if (ts := first_activity.get(h.wallet)) is not None]
    coverage = _coverage(len(ages), len(holders))
    if not ages:
        return not_visible(name, "no first activity resolved", coverage)
    day = sum(1 for a in ages if a < config.WALLET_NEW_DAY)
    week = sum(1 for a in ages if a < config.WALLET_NEW_WEEK)
    share_day, share_week = pct(day, len(ages)), pct(week, len(ages))
    return MetricResult(
        name=name, status="ok", coverage=coverage,
        display=f"{share_day:.0f}% of these wallets were created today, {share_week:.0f}% this week",
        raw={"resolved": len(ages), "under_24h": day, "under_7d": week,
             "share_under_24h": share_day / 100, "share_under_7d": share_week / 100},
    )


# --- 3. deployer history ---------------------------------------------------------------


def mint_outcome_pct(meta: MintMeta) -> float | None:
    if meta.first_price is None or meta.last_price is None or meta.first_price <= 0:
        return None
    return (meta.last_price - meta.first_price) / meta.first_price * 100


def lifespan_days(meta: MintMeta) -> float | None:
    if meta.first_trade_ts is None or meta.last_trade_ts is None:
        return None
    return (meta.last_trade_ts - meta.first_trade_ts).total_seconds() / 86400


def deployer_history(graph: FundingGraph | None, linked_meta: Mapping[str, MintMeta | None]) -> MetricResult:
    name = MetricName.DEPLOYER
    if graph is None:
        return not_visible(name, "creator or funding graph not resolved")
    if not graph.linked_mints:
        return not_visible(name, "no linked history visible", f"{len(graph.wallets)} wallets walked")

    metas = [m for mint in graph.linked_mints if (m := linked_meta.get(mint)) is not None]
    outcomes = [o for m in metas if (o := mint_outcome_pct(m)) is not None]
    lifespans = [d for m in metas if (d := lifespan_days(m)) is not None]
    coverage = f"{len(outcomes)} of {len(graph.linked_mints)} mints priced, {len(graph.wallets)} wallets walked"
    if not outcomes:
        return not_visible(name, "linked mints have no price history", coverage)

    median_outcome = statistics.median(outcomes)
    longest = max(lifespans) if lifespans else None
    display = (f"this deployer is linked to {fmt_count(len(graph.linked_mints), 'prior mint')}, "
               f"median outcome {median_outcome:+.0f}%")
    if longest is not None:
        display += f", longest survivor {longest:.0f} days"
    if graph.truncated:
        display += " (graph capped)"
    return MetricResult(name=name, status="ok", display=display, coverage=coverage, raw={
        "linked_mints": len(graph.linked_mints), "priced": len(outcomes), "median_outcome_pct": median_outcome,
        "longest_survivor_days": longest, "wallets_walked": len(graph.wallets), "truncated": graph.truncated,
    })


# --- 4. overlap -------------------------------------------------------------------------


def overlap(holders: Sequence[Holder], holdings: Mapping[str, Sequence[Holding] | None], *, exclude_mint: str,
            ignore_mints: frozenset[str] = config.OVERLAP_IGNORE_MINTS,
            top_k: int = config.OVERLAP_TOP_K) -> MetricResult:
    name = MetricName.OVERLAP
    sets = [
        {h.mint for h in held if h.amount > 0 and h.mint != exclude_mint and h.mint not in ignore_mints}
        for w in holders if (held := holdings.get(w.wallet)) is not None
    ]
    n = len(sets)
    coverage = _coverage(n, len(holders))
    if n == 0:
        return not_visible(name, "no current holdings resolved", coverage)

    counts: Counter[str] = Counter(m for s in sets for m in s)
    top = sorted(counts, key=lambda m: (-counts[m], m))[:top_k]
    all_top = sum(1 for s in sets if top and set(top) <= s)
    if not top:
        display = f"none of {n} wallets share another token"
    else:
        display = f"{all_top} of {n} of these wallets also hold the same {fmt_count(len(top), 'token')}"
    return MetricResult(name=name, status="ok", display=display, coverage=coverage, raw={
        "wallets": n, "holding_all_top": all_top, "share_holding_all_top": all_top / n,
        "top": [{"mint": m, "holders": counts[m], "share": counts[m] / n} for m in top],
    })


# --- 5. hold time -------------------------------------------------------------------------


def hold_time(positions_by_wallet: Mapping[str, Sequence[Position]], *,
              fast_exit_seconds: int = config.FAST_EXIT_SECONDS) -> MetricResult:
    name = MetricName.HOLD_TIME
    durations = [d for ps in positions_by_wallet.values() for p in ps if (d := p.duration_seconds) is not None]
    coverage = f"{len(durations)} closed positions from {len(positions_by_wallet)} wallets"
    if not durations:
        return not_visible(name, "no completed prior positions", coverage)
    median = statistics.median(durations)
    fast = sum(1 for d in durations if d < fast_exit_seconds)
    return MetricResult(
        name=name, status="ok", coverage=coverage,
        display=f"median prior position lasted {fmt_duration(median)}, "
                f"{pct(fast, len(durations)):.0f}% closed under {fast_exit_seconds} seconds",
        raw={"positions": len(durations), "median_seconds": median, "under_fast": fast,
             "share_under_fast": fast / len(durations)},
    )


# --- 6. exit percentile ----------------------------------------------------------------------


def exit_percentile(position: Position, meta: MintMeta) -> float | None:
    """Where the average sell price sat in the token's observed range, 0..100."""
    if not position.closed or position.avg_sell_price is None:
        return None
    low, high = meta.price_low, meta.price_high
    if low is None or high is None or high <= low:
        return None
    if position.quote and meta.quote and position.quote != meta.quote:
        return None
    raw = (position.avg_sell_price - low) / (high - low) * 100
    return min(100.0, max(0.0, raw))


def crowd_exit_percentile(positions_by_wallet: Mapping[str, Sequence[Position]],
                          mint_meta: Mapping[str, MintMeta | None]) -> MetricResult:
    name = MetricName.EXIT_PERCENTILE
    closed = [p for ps in positions_by_wallet.values() for p in ps if p.closed]
    values = [v for p in closed if (meta := mint_meta.get(p.mint)) is not None
              and (v := exit_percentile(p, meta)) is not None]
    coverage = f"{len(values)} of {len(closed)} exits priced"
    if not values:
        return not_visible(name, "no priced exits" if closed else "no completed prior positions", coverage)
    median = statistics.median(values)
    return MetricResult(
        name=name, status="ok", coverage=coverage,
        display=f"this crowd's median exit sits at the {ordinal(round(median))} percentile of a token's range",
        raw={"exits": len(values), "median_percentile": median},
    )
