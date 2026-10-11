"""Caching wrapper around any provider.

Two layers:
  * an in-run memo of tasks, so a wallet is never fetched twice in one run, even
    when two metrics ask for it at the same moment;
  * the SQLite cache, persisted between runs, with per-kind TTLs from config.
Errors are never cached.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from .. import config
from ..cache import Cache
from ..errors import NotSupported
from ..models import Holder, Holding, MintMeta, Trade, parse_ts
from .base import FundingGraphProvider, TokenDataProvider

T = TypeVar("T")


class CachedProvider(TokenDataProvider, FundingGraphProvider):
    def __init__(self, inner: TokenDataProvider, cache: Cache | None):
        self.inner = inner
        self.cache = cache
        self.name = inner.name
        self._memo: dict[tuple[str, str], asyncio.Task[Any]] = {}

    @property
    def supports_funding_graph(self) -> bool:
        return isinstance(self.inner, FundingGraphProvider)

    async def _cached(self, ns: str, key: str, fetch: Callable[[], Awaitable[T]],
                      dump: Callable[[T], Any], load: Callable[[Any], T]) -> T:
        memo_key = (ns, key)
        if memo_key not in self._memo:
            self._memo[memo_key] = asyncio.ensure_future(self._fetch(ns, key, fetch, dump, load))
        task = self._memo[memo_key]
        try:
            return await asyncio.shield(task)
        except Exception:
            self._memo.pop(memo_key, None)  # let a later call retry
            raise

    async def _fetch(self, ns, key, fetch, dump, load):
        cache_key = f"{self.inner.name}:{key}"
        if self.cache is not None:
            hit = self.cache.get(ns, cache_key, config.CACHE_TTL[ns])
            if hit is not Cache.MISS:
                return load(hit)
        value = await fetch()
        if self.cache is not None:
            self.cache.set(ns, cache_key, dump(value))
        return value

    async def get_top_holders(self, mint: str, limit: int) -> list[Holder]:
        return await self._cached(
            "top_holders", f"{mint}:{limit}", lambda: self.inner.get_top_holders(mint, limit),
            lambda v: [h.to_dict() for h in v], lambda v: [Holder.from_dict(d) for d in v])

    async def get_wallet_first_activity(self, wallet: str) -> datetime | None:
        return await self._cached(
            "first_activity", wallet, lambda: self.inner.get_wallet_first_activity(wallet),
            lambda v: v.isoformat() if v else None, parse_ts)

    async def get_wallet_dex_trades(self, wallet: str, since: datetime) -> list[Trade]:
        return await self._cached(
            "dex_trades", f"{wallet}:{since.date().isoformat()}",
            lambda: self.inner.get_wallet_dex_trades(wallet, since),
            lambda v: [t.to_dict() for t in v], lambda v: [Trade.from_dict(d) for d in v])

    async def get_wallet_current_holdings(self, wallet: str) -> list[Holding]:
        return await self._cached(
            "holdings", wallet, lambda: self.inner.get_wallet_current_holdings(wallet),
            lambda v: [h.to_dict() for h in v], lambda v: [Holding.from_dict(d) for d in v])

    async def get_mint_metadata(self, mint: str) -> MintMeta:
        return await self._cached(
            "mint_meta", mint, lambda: self.inner.get_mint_metadata(mint),
            lambda v: v.to_dict(), MintMeta.from_dict)

    async def get_mint_creator(self, mint: str) -> str | None:
        return await self._cached("mint_creator", mint, lambda: self.inner.get_mint_creator(mint),
                                  lambda v: v, lambda v: v)

    def _funding(self) -> FundingGraphProvider:
        if not isinstance(self.inner, FundingGraphProvider):
            raise NotSupported(f"{self.inner.name} has no funding graph")
        return self.inner

    async def get_first_funder(self, wallet: str) -> str | None:
        return await self._cached("first_funder", wallet, lambda: self._funding().get_first_funder(wallet),
                                  lambda v: v, lambda v: v)

    async def get_wallets_funded_by(self, funder: str, limit: int) -> list[str]:
        return await self._cached("funded_by", f"{funder}:{limit}",
                                  lambda: self._funding().get_wallets_funded_by(funder, limit),
                                  list, list)

    async def get_mints_created_by(self, wallet: str, limit: int) -> list[str]:
        return await self._cached("created_by", f"{wallet}:{limit}",
                                  lambda: self._funding().get_mints_created_by(wallet, limit),
                                  list, list)

    async def aclose(self) -> None:
        await self.inner.aclose()
