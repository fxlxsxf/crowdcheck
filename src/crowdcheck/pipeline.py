"""Fetch everything, then hand plain data to the pure metric functions."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from . import config, metrics
from .errors import CrowdcheckError, ProviderError
from .models import FundingGraph, Holder, MetricName, MetricResult, MintMeta, Report
from .providers.cached import CachedProvider
from .scoring import score
from .verdict import CLOSING_LINE, verdict

T = TypeVar("T")


@dataclass
class RunOptions:
    top_n: int = config.TOP_N
    funding_graph: bool = True
    prior_mint_cap: int = config.PRIOR_MINT_CAP
    lookback: timedelta = config.TRADE_LOOKBACK
    now: datetime | None = None


@dataclass
class _Failures:
    """Counts failed calls per kind so the report can say what went missing."""
    counts: Counter[str] = field(default_factory=Counter)
    reasons: dict[str, str] = field(default_factory=dict)

    async def guard(self, kind: str, call: Awaitable[T]) -> T | None:
        try:
            return await call
        except ProviderError as exc:
            self.counts[kind] += 1
            self.reasons.setdefault(kind, str(exc))
            return None

    def notes(self) -> list[str]:
        return [f"{n} {kind} calls failed ({self.reasons[kind]})" for kind, n in sorted(self.counts.items())]


async def walk_funding_graph(provider: CachedProvider, creator: str, *, target_mint: str,
                             depth: int = config.FUNDING_GRAPH_DEPTH,
                             max_wallets: int = config.FUNDING_GRAPH_MAX_WALLETS,
                             failures: _Failures | None = None) -> tuple[FundingGraph, list[str]]:
    """creator -> the wallet that first funded it -> other wallets that funder funded.

    If the funder sent SOL to more than `max_wallets` wallets it is treated as a
    hub (an exchange or a service) and its other recipients are NOT linked: that
    link would tie the deployer to strangers.
    """
    failures = failures or _Failures()
    notes: list[str] = []
    wallets = [creator]
    funder = None
    truncated = False

    if depth >= 1:
        funder = await failures.guard("first funder", provider.get_first_funder(creator))
        if funder and funder not in wallets:
            wallets.append(funder)
    if depth >= 2 and funder:
        funded = await failures.guard("funded-by", provider.get_wallets_funded_by(funder, max_wallets + 1)) or []
        if len(funded) > max_wallets:
            truncated = True
            notes.append("deployer's funder sent SOL to more than "
                         f"{max_wallets} wallets, treated as an exchange or service and not expanded")
        else:
            for w in funded:
                if len(wallets) >= max_wallets:
                    truncated = True
                    break
                if w not in wallets:
                    wallets.append(w)

    created = await asyncio.gather(*(failures.guard("created-by", provider.get_mints_created_by(w, max_wallets))
                                     for w in wallets))
    linked: list[str] = []
    for mints in created:
        for m in mints or ():
            if m != target_mint and m not in linked:
                linked.append(m)
    return FundingGraph(creator=creator, funder=funder, wallets=wallets, linked_mints=linked,
                        truncated=truncated), notes


async def run(provider: CachedProvider, mint: str, opts: RunOptions | None = None) -> Report:
    opts = opts or RunOptions()
    now = opts.now or datetime.now(timezone.utc)
    failures = _Failures()
    notes: list[str] = []

    target_meta = await failures.guard("target mint metadata", provider.get_mint_metadata(mint))
    try:
        holders: list[Holder] = await provider.get_top_holders(mint, opts.top_n)
    except ProviderError as exc:
        raise CrowdcheckError(f"could not load holders: {exc}") from None
    if not holders:
        raise CrowdcheckError("no holders found for this mint")
    if len(holders) < opts.top_n:
        notes.append(f"only {len(holders)} holders found, fewer than the {opts.top_n} requested")

    wallets = [h.wallet for h in holders]
    since = now - opts.lookback

    first_activity, trades, holdings = await asyncio.gather(
        asyncio.gather(*(failures.guard("first activity", provider.get_wallet_first_activity(w)) for w in wallets)),
        asyncio.gather(*(failures.guard("trade history", provider.get_wallet_dex_trades(w, since)) for w in wallets)),
        asyncio.gather(*(failures.guard("holdings", provider.get_wallet_current_holdings(w)) for w in wallets)),
    )
    first_by_wallet = dict(zip(wallets, first_activity))
    trades_by_wallet = dict(zip(wallets, trades))
    holdings_by_wallet = dict(zip(wallets, holdings))

    resolved_trades = {w: t for w, t in trades_by_wallet.items() if t is not None}
    positions = {w: metrics.build_positions(t, exclude_mint=mint) for w, t in resolved_trades.items()}

    prior, cap_hit = metrics.prior_mints(trades_by_wallet, exclude_mint=mint, cap=opts.prior_mint_cap)
    metas = await asyncio.gather(*(failures.guard("prior mint metadata", provider.get_mint_metadata(m))
                                   for m in prior))
    mint_meta: dict[str, MintMeta | None] = dict(zip(prior, metas))

    results: list[MetricResult] = [
        metrics.crowd_track_record(prior, mint_meta, cap_hit=cap_hit, now=now,
                                   wallets_resolved=len(resolved_trades), wallets_total=len(wallets)),
        metrics.wallet_age(holders, first_by_wallet, now=now),
        await _deployer(provider, mint, target_meta, opts, failures, notes),
        metrics.overlap(holders, holdings_by_wallet, exclude_mint=mint),
        metrics.hold_time(positions),
        metrics.crowd_exit_percentile(positions, mint_meta),
    ]
    notes.extend(getattr(provider.inner, "notes", []))
    notes.extend(failures.notes())
    return Report(mint=mint, symbol=target_meta.symbol if target_meta else None, top_n=opts.top_n,
                  holders_found=len(holders), results=results, score=score(results), verdict=verdict(results),
                  closing_line=CLOSING_LINE, generated_at=now, notes=notes)


async def _deployer(provider: CachedProvider, mint: str, target_meta: MintMeta | None, opts: RunOptions,
                    failures: _Failures, notes: list[str]) -> MetricResult:
    if not opts.funding_graph:
        return metrics.not_visible(MetricName.DEPLOYER, "funding graph disabled")
    if not provider.supports_funding_graph:
        return metrics.not_visible(MetricName.DEPLOYER, f"{provider.name} has no funding graph")
    creator = (target_meta.creator if target_meta else None) or \
        await failures.guard("mint creator", provider.get_mint_creator(mint))
    if not creator:
        return metrics.not_visible(MetricName.DEPLOYER, "mint creator not resolved")
    graph, graph_notes = await walk_funding_graph(provider, creator, target_mint=mint, failures=failures)
    notes.extend(graph_notes)
    metas = await asyncio.gather(*(failures.guard("linked mint metadata", provider.get_mint_metadata(m))
                                   for m in graph.linked_mints))
    return metrics.deployer_history(graph, dict(zip(graph.linked_mints, metas)))
