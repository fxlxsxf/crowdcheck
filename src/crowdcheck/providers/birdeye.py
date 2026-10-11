"""Birdeye backend, used as a fallback (and the better source for mint price history).

Docs: https://docs.birdeye.so . Key from BIRDEYE_API_KEY, sent as a header.
Birdeye has no endpoint for a wallet's first on-chain activity or for a funding
graph, so those calls raise NotSupported and the metrics show "not visible".
Response parsing is defensive: missing fields become None, never a crash.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..errors import NotSupported, ProviderError
from ..http import HttpClient
from ..models import Holder, Holding, MintMeta, Trade, parse_ts
from .base import TokenDataProvider

BASE = "https://public-api.birdeye.so"


def _items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    if isinstance(inner, dict):
        items = inner.get("items")
        return items if isinstance(items, list) else []
    return inner if isinstance(inner, list) else []


def parse_birdeye_trade(item: dict[str, Any], wallet: str) -> Trade | None:
    """One item from /trader/txs/seek_by_time. Base is the token, quote is SOL/USD side."""
    base, quote = item.get("base") or {}, item.get("quote") or {}
    mint = base.get("address")
    change = base.get("ui_change_amount")
    if not mint or change in (None, 0):
        return None
    change = float(change)
    price = base.get("price")
    return Trade(wallet=wallet, mint=mint, side="buy" if change > 0 else "sell",
                 ts=parse_ts(item.get("block_unix_time")), token_amount=abs(change),
                 price=float(price) if price is not None else None, quote="USD" if price is not None else None,
                 signature=item.get("tx_hash"))


class BirdeyeProvider(TokenDataProvider):
    name = "birdeye"

    def __init__(self, api_key: str, http: HttpClient | None = None):
        self.http = http or HttpClient(headers={"X-API-KEY": api_key, "x-chain": "solana",
                                                "accept": "application/json"})
        self.notes: list[str] = []

    async def _get(self, path: str, **params: Any) -> Any:
        data = await self.http.get(f"{BASE}{path}", params=params)
        if isinstance(data, dict) and data.get("success") is False:
            raise ProviderError(f"birdeye {path}: {str(data.get('message', 'failed'))[:80]}")
        return data

    async def get_top_holders(self, mint: str, limit: int) -> list[Holder]:
        holders: list[Holder] = []
        offset = 0
        while len(holders) < limit:
            page = _items(await self._get("/defi/v3/token/holder", address=mint, offset=offset,
                                          limit=min(100, limit - len(holders))))
            for it in page:
                if it.get("owner"):
                    holders.append(Holder(wallet=it["owner"], amount=float(it.get("ui_amount") or 0)))
            if len(page) < 100:
                break
            offset += len(page)
        return holders[:limit]

    async def get_wallet_first_activity(self, wallet: str) -> datetime | None:
        raise NotSupported("birdeye has no first-activity lookup")

    async def get_wallet_dex_trades(self, wallet: str, since: datetime) -> list[Trade]:
        trades: list[Trade] = []
        offset = 0
        for _ in range(5):
            page = _items(await self._get("/trader/txs/seek_by_time", address=wallet, offset=offset, limit=100,
                                          after_time=int(since.timestamp())))
            trades.extend(t for it in page if (t := parse_birdeye_trade(it, wallet)))
            if len(page) < 100:
                break
            offset += len(page)
        return trades

    async def get_wallet_current_holdings(self, wallet: str) -> list[Holding]:
        return [Holding(mint=it["address"], amount=float(it.get("uiAmount") or 0))
                for it in _items(await self._get("/v1/wallet/token_list", wallet=wallet)) if it.get("address")]

    async def get_mint_metadata(self, mint: str) -> MintMeta:
        overview = (await self._get("/defi/token_overview", address=mint) or {}).get("data") or {}
        creation = {}
        try:
            creation = (await self._get("/defi/token_creation_info", address=mint) or {}).get("data") or {}
        except ProviderError:
            pass
        created = parse_ts(creation.get("blockUnixTime"))
        start = int(created.timestamp()) if created else 0
        points = _items(await self._get("/defi/history_price", address=mint, address_type="token", type="1D",
                                        time_from=start, time_to=int(datetime.now(timezone.utc).timestamp())))
        series = sorted((parse_ts(p.get("unixTime")), float(p["value"])) for p in points
                        if p.get("unixTime") is not None and p.get("value") is not None)
        last_trade = parse_ts(overview.get("lastTradeUnixTime"))
        prices = [v for _, v in series]
        return MintMeta(
            mint=mint, symbol=overview.get("symbol"), creator=creation.get("owner"),
            first_trade_ts=series[0][0] if series else created,
            last_trade_ts=last_trade or (series[-1][0] if series else None),
            first_price=prices[0] if prices else None, last_price=prices[-1] if prices else None,
            price_low=min(prices) if prices else None, price_high=max(prices) if prices else None,
            quote="USD" if prices else None, trade_count=len(series) or None, history_complete=bool(series),
        )

    async def get_mint_creator(self, mint: str) -> str | None:
        data = (await self._get("/defi/token_creation_info", address=mint) or {}).get("data") or {}
        return data.get("owner")

    async def aclose(self) -> None:
        await self.http.aclose()
