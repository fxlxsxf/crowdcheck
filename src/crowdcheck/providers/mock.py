"""Fixture-backed provider. Used by every test; makes no network calls.

A scenario is a directory with up to four JSON files:

  holders.json  {"<mint>": [{"wallet", "amount", "share_of_supply"}, ...]}
  wallets.json  {"<wallet>": {"first_activity", "trades": [...], "holdings": [...]}}
  mints.json    {"<mint>": {MintMeta fields}}
  funding.json  {"first_funder": {wallet: funder}, "funded_by": {funder: [wallets]},
                 "created_by": {wallet: [mints]}}

Missing files, wallets or fields behave like a provider that has no data.
`fail` names calls that should raise, e.g. {"get_wallet_dex_trades:W3": RateLimited("...")}.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import ProviderError
from ..models import Holder, Holding, MintMeta, Trade, parse_ts
from .base import FundingGraphProvider, TokenDataProvider


class MockProvider(TokenDataProvider, FundingGraphProvider):
    name = "mock"

    def __init__(self, scenario_dir: str | Path, fail: dict[str, Exception] | None = None):
        self.dir = Path(scenario_dir)
        if not self.dir.is_dir():
            raise ProviderError(f"fixture directory not found: {self.dir}")
        self.holders = self._load("holders.json")
        self.wallets = self._load("wallets.json")
        self.mints = self._load("mints.json")
        self.funding = self._load("funding.json")
        self.fail = fail or {}
        self.calls: Counter[str] = Counter()

    def _load(self, name: str) -> dict[str, Any]:
        path = self.dir / name
        return json.loads(path.read_text()) if path.exists() else {}

    def _hit(self, method: str, key: str) -> None:
        self.calls[f"{method}:{key}"] += 1
        err = self.fail.get(f"{method}:{key}") or self.fail.get(f"{method}:*")
        if err:
            raise err

    async def get_top_holders(self, mint: str, limit: int) -> list[Holder]:
        self._hit("get_top_holders", mint)
        rows = [Holder.from_dict(d) for d in self.holders.get(mint, [])]
        return sorted(rows, key=lambda h: -h.amount)[:limit]

    async def get_wallet_first_activity(self, wallet: str) -> datetime | None:
        self._hit("get_wallet_first_activity", wallet)
        return parse_ts(self.wallets.get(wallet, {}).get("first_activity"))

    async def get_wallet_dex_trades(self, wallet: str, since: datetime) -> list[Trade]:
        self._hit("get_wallet_dex_trades", wallet)
        trades = []
        for d in self.wallets.get(wallet, {}).get("trades", []):
            try:
                t = Trade.from_dict({"wallet": wallet, **d})
            except KeyError:
                continue  # partial row without mint or side: skip it, like a real parser would
            if t.ts is None or t.ts >= since:
                trades.append(t)
        return trades

    async def get_wallet_current_holdings(self, wallet: str) -> list[Holding]:
        self._hit("get_wallet_current_holdings", wallet)
        return [Holding.from_dict(d) for d in self.wallets.get(wallet, {}).get("holdings", []) if "mint" in d]

    async def get_mint_metadata(self, mint: str) -> MintMeta:
        self._hit("get_mint_metadata", mint)
        if mint not in self.mints:
            raise ProviderError("mint not found")
        return MintMeta.from_dict({"mint": mint, **self.mints[mint]})

    async def get_mint_creator(self, mint: str) -> str | None:
        self._hit("get_mint_creator", mint)
        return self.mints.get(mint, {}).get("creator")

    async def get_first_funder(self, wallet: str) -> str | None:
        self._hit("get_first_funder", wallet)
        return self.funding.get("first_funder", {}).get(wallet)

    async def get_wallets_funded_by(self, funder: str, limit: int) -> list[str]:
        self._hit("get_wallets_funded_by", funder)
        return list(self.funding.get("funded_by", {}).get(funder, []))[:limit]

    async def get_mints_created_by(self, wallet: str, limit: int) -> list[str]:
        self._hit("get_mints_created_by", wallet)
        return list(self.funding.get("created_by", {}).get(wallet, []))[:limit]
