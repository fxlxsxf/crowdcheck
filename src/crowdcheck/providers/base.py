from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Holder, Holding, MintMeta, Trade


class TokenDataProvider(ABC):
    """Everything the six metrics need, except the funding graph."""

    name: str = "base"

    @abstractmethod
    async def get_top_holders(self, mint: str, limit: int) -> list[Holder]: ...

    @abstractmethod
    async def get_wallet_first_activity(self, wallet: str) -> datetime | None: ...

    @abstractmethod
    async def get_wallet_dex_trades(self, wallet: str, since: datetime) -> list[Trade]: ...

    @abstractmethod
    async def get_wallet_current_holdings(self, wallet: str) -> list[Holding]: ...

    @abstractmethod
    async def get_mint_metadata(self, mint: str) -> MintMeta:
        """Creator, first and last trade timestamps, first/last/low/high price."""

    @abstractmethod
    async def get_mint_creator(self, mint: str) -> str | None: ...

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass


class FundingGraphProvider(ABC):
    """Optional extra interface for metric 3. A backend that lacks it simply
    leaves metric 3 "not visible"."""

    @abstractmethod
    async def get_first_funder(self, wallet: str) -> str | None:
        """The wallet that sent `wallet` its first SOL."""

    @abstractmethod
    async def get_wallets_funded_by(self, funder: str, limit: int) -> list[str]:
        """Other wallets that received SOL from `funder`."""

    @abstractmethod
    async def get_mints_created_by(self, wallet: str, limit: int) -> list[str]:
        """Mints this wallet created."""
