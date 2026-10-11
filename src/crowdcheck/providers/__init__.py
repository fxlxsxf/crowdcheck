"""Provider construction. API keys come from the environment only."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ..errors import MissingApiKey, ProviderError
from ..models import Holder, Holding, MintMeta, Trade
from .base import FundingGraphProvider, TokenDataProvider


class FallbackProvider(TokenDataProvider, FundingGraphProvider):
    """Try `primary`; on any ProviderError (including NotSupported) try `fallback`."""

    def __init__(self, primary: TokenDataProvider, fallback: TokenDataProvider):
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}+{fallback.name}"

    @property
    def notes(self) -> list[str]:
        return [*getattr(self.primary, "notes", []), *getattr(self.fallback, "notes", [])]

    async def _try(self, method: str, *args):
        try:
            return await getattr(self.primary, method)(*args)
        except ProviderError:
            if not hasattr(self.fallback, method):
                raise
            return await getattr(self.fallback, method)(*args)

    async def get_top_holders(self, mint: str, limit: int) -> list[Holder]:
        return await self._try("get_top_holders", mint, limit)

    async def get_wallet_first_activity(self, wallet: str) -> datetime | None:
        return await self._try("get_wallet_first_activity", wallet)

    async def get_wallet_dex_trades(self, wallet: str, since: datetime) -> list[Trade]:
        return await self._try("get_wallet_dex_trades", wallet, since)

    async def get_wallet_current_holdings(self, wallet: str) -> list[Holding]:
        return await self._try("get_wallet_current_holdings", wallet)

    async def get_mint_metadata(self, mint: str) -> MintMeta:
        return await self._try("get_mint_metadata", mint)

    async def get_mint_creator(self, mint: str) -> str | None:
        return await self._try("get_mint_creator", mint)

    async def get_first_funder(self, wallet: str) -> str | None:
        return await self.primary.get_first_funder(wallet)  # type: ignore[attr-defined]

    async def get_wallets_funded_by(self, funder: str, limit: int) -> list[str]:
        return await self.primary.get_wallets_funded_by(funder, limit)  # type: ignore[attr-defined]

    async def get_mints_created_by(self, wallet: str, limit: int) -> list[str]:
        return await self.primary.get_mints_created_by(wallet, limit)  # type: ignore[attr-defined]

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()


def _key(variable: str) -> str:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise MissingApiKey(variable)
    return value


def build_provider(name: str, *, fixtures: Path | None = None) -> TokenDataProvider:
    if name == "mock":
        from .mock import MockProvider
        if fixtures is None:
            raise ProviderError("--fixtures is required with --provider mock")
        return MockProvider(fixtures)
    if name == "helius":
        from .helius import HeliusProvider
        helius = HeliusProvider(_key("HELIUS_API_KEY"))
        if os.environ.get("BIRDEYE_API_KEY", "").strip():
            from .birdeye import BirdeyeProvider
            return FallbackProvider(helius, BirdeyeProvider(_key("BIRDEYE_API_KEY")))
        return helius
    if name == "birdeye":
        from .birdeye import BirdeyeProvider
        return BirdeyeProvider(_key("BIRDEYE_API_KEY"))
    raise ProviderError(f"unknown provider {name!r}; use helius, birdeye or mock")
