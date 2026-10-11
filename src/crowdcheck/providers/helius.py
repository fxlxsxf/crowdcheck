"""Helius backend: Solana RPC + DAS + Enhanced Transactions.

Docs: https://docs.helius.dev . The key is read from HELIUS_API_KEY by the CLI
and only ever placed in request URLs, which are never printed or logged.

Known limits of reconstructing history from raw chain data, all visible in
config.py as page caps:
  * prices are derived from each swap's SOL or USD leg, so they include fees and
    tips and are approximate;
  * a mint's trade history is read from transactions that reference the mint
    account; some AMMs do not reference it, so older history can be missing.
    When nothing is found this backend raises, so a fallback (Birdeye) is used.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .. import config
from ..errors import ProviderError
from ..http import HttpClient
from ..models import Holder, Holding, MintMeta, Trade, parse_ts
from .base import FundingGraphProvider, TokenDataProvider

SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1tTXsUz7Ry8Nfxt"
WSOL = "So11111111111111111111111111111111111111112"
USD_MINTS = frozenset({"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                       "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"})
QUOTE_MINTS = USD_MINTS | {WSOL}
FUNGIBLE_INTERFACES = {"FungibleToken", "FungibleAsset"}


def parse_swap_trades(tx: dict[str, Any], wallet: str) -> list[Trade]:
    """Turn one Helius enhanced transaction into trades for `wallet`.

    Net token flows into and out of the wallet are computed per mint. The SOL
    (native + wSOL) or USD (USDC/USDT) leg is the quote. A price is assigned only
    when exactly one non-quote mint moved, so it is never split by guesswork.
    """
    ts = parse_ts(tx.get("timestamp"))
    nets: dict[str, float] = defaultdict(float)
    for tt in tx.get("tokenTransfers") or ():
        mint, amount = tt.get("mint"), tt.get("tokenAmount")
        if not mint or amount is None:
            continue
        if tt.get("toUserAccount") == wallet:
            nets[mint] += float(amount)
        if tt.get("fromUserAccount") == wallet:
            nets[mint] -= float(amount)
    sol = nets.pop(WSOL, 0.0)
    for nt in tx.get("nativeTransfers") or ():
        lamports = nt.get("amount") or 0
        if nt.get("toUserAccount") == wallet:
            sol += lamports / 1e9
        if nt.get("fromUserAccount") == wallet:
            sol -= lamports / 1e9
    usd = sum(nets.pop(m, 0.0) for m in USD_MINTS)

    moved = {m: n for m, n in nets.items() if abs(n) > 0}
    trades = []
    for mint, net in moved.items():
        price = quote = None
        if len(moved) == 1:
            if usd and (usd > 0) != (net > 0):
                price, quote = abs(usd) / abs(net), "USD"
            elif sol and (sol > 0) != (net > 0):
                price, quote = abs(sol) / abs(net), "SOL"
        trades.append(Trade(wallet=wallet, mint=mint, side="buy" if net > 0 else "sell", ts=ts,
                            token_amount=abs(net), price=price, quote=quote, signature=tx.get("signature")))
    return trades


class HeliusProvider(TokenDataProvider, FundingGraphProvider):
    name = "helius"

    def __init__(self, api_key: str, http: HttpClient | None = None,
                 rpc_url: str = "https://mainnet.helius-rpc.com/", api_url: str = "https://api.helius.xyz/v0"):
        self._key = api_key
        self.http = http or HttpClient()
        self.rpc_url = rpc_url
        self.api_url = api_url
        self.notes: list[str] = []
        self._oldest: dict[str, tuple[list[dict[str, Any]], bool]] = {}

    # --- transport ---------------------------------------------------------------

    async def _rpc(self, method: str, params: Any) -> Any:
        body = {"jsonrpc": "2.0", "id": "crowdcheck", "method": method, "params": params}
        data = await self.http.post(self.rpc_url, params={"api-key": self._key}, json=body)
        if not isinstance(data, dict):
            raise ProviderError(f"{method}: unexpected response")
        if "error" in data:
            msg = (data["error"] or {}).get("message", "error") if isinstance(data["error"], dict) else "error"
            raise ProviderError(f"{method}: {msg[:80]}")
        return data.get("result")

    async def _enhanced(self, address: str, *, tx_type: str | None, before: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"api-key": self._key, "limit": 100}
        if tx_type:
            params["type"] = tx_type
        if before:
            params["before"] = before
        data = await self.http.get(f"{self.api_url}/addresses/{address}/transactions", params=params)
        return data if isinstance(data, list) else []

    async def _parse(self, signatures: list[str]) -> list[dict[str, Any]]:
        if not signatures:
            return []
        data = await self.http.post(f"{self.api_url}/transactions", params={"api-key": self._key},
                                    json={"transactions": signatures})
        return data if isinstance(data, list) else []

    async def _oldest_signatures(self, address: str) -> tuple[list[dict[str, Any]], bool]:
        """Last page of signatures, oldest last. Returns (page, reached_the_beginning)."""
        if address in self._oldest:
            return self._oldest[address]
        before, last_page = None, []
        for _ in range(config.SIGNATURE_PAGE_CAP):
            opts: dict[str, Any] = {"limit": 1000}
            if before:
                opts["before"] = before
            page = await self._rpc("getSignaturesForAddress", [address, opts]) or []
            if page:
                last_page = page
            if len(page) < 1000:
                self._oldest[address] = (last_page, True)
                return last_page, True
            before = page[-1]["signature"]
        self._oldest[address] = (last_page, False)
        return last_page, False

    # --- TokenDataProvider ----------------------------------------------------------

    async def get_top_holders(self, mint: str, limit: int) -> list[Holder]:
        supply = await self._rpc("getTokenSupply", [mint])
        value = (supply or {}).get("value") or {}
        decimals = int(value.get("decimals") or 0)
        total = float(value["uiAmount"]) if value.get("uiAmount") else None

        by_owner: dict[str, float] = defaultdict(float)
        complete = False
        for page in range(1, config.HOLDER_SCAN_PAGE_CAP + 1):
            res = await self._rpc("getTokenAccounts", {"mint": mint, "page": page, "limit": 1000})
            accounts = (res or {}).get("token_accounts") or []
            for acc in accounts:
                if acc.get("owner") and acc.get("amount"):
                    by_owner[acc["owner"]] += int(acc["amount"]) / 10 ** decimals
            if len(accounts) < 1000:
                complete = True
                break
        if not complete:
            self.notes.append(f"holder ranking is from a partial scan of {config.HOLDER_SCAN_PAGE_CAP * 1000} "
                              "token accounts")

        ranked = sorted((o for o in by_owner if o not in config.EXCLUDED_OWNERS), key=lambda o: -by_owner[o])
        holders: list[Holder] = []
        # Keep only owners that are System-program wallets: pools, vaults and PDAs drop out here.
        for i in range(0, len(ranked), 100):
            if len(holders) >= limit:
                break
            chunk = ranked[i:i + 100]
            res = await self._rpc("getMultipleAccounts", [chunk, {"encoding": "base64", "dataSlice":
                                                                   {"offset": 0, "length": 0}}])
            infos = (res or {}).get("value") or []
            for owner, info in zip(chunk, infos):
                if info and info.get("owner") == SYSTEM_PROGRAM and len(holders) < limit:
                    amt = by_owner[owner]
                    holders.append(Holder(wallet=owner, amount=amt, share_of_supply=amt / total if total else None))
        return holders

    async def get_wallet_first_activity(self, wallet: str) -> datetime | None:
        page, complete = await self._oldest_signatures(wallet)
        times = [s["blockTime"] for s in page if s.get("blockTime")]
        if not times:
            return None
        oldest = parse_ts(min(times))
        if complete:
            return oldest
        # Paging stopped early: we only know the wallet is at least this old. That is
        # enough to say "older than a week", not enough to say "new".
        if oldest and datetime.now(timezone.utc) - oldest > config.WALLET_NEW_WEEK:
            return oldest
        return None

    async def get_wallet_dex_trades(self, wallet: str, since: datetime) -> list[Trade]:
        trades: list[Trade] = []
        before = None
        for _ in range(config.WALLET_TRADE_PAGE_CAP):
            txs = await self._enhanced(wallet, tx_type="SWAP", before=before)
            if not txs:
                break
            for tx in txs:
                ts = parse_ts(tx.get("timestamp"))
                if ts and ts < since:
                    return trades
                trades.extend(parse_swap_trades(tx, wallet))
            before = txs[-1].get("signature")
            if len(txs) < 100 or not before:
                break
        return trades

    async def get_wallet_current_holdings(self, wallet: str) -> list[Holding]:
        holdings: dict[str, float] = defaultdict(float)
        for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            res = await self._rpc("getTokenAccountsByOwner",
                                  [wallet, {"programId": program}, {"encoding": "jsonParsed"}])
            for acc in (res or {}).get("value") or []:
                info = (((acc.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
                amount = (info.get("tokenAmount") or {}).get("uiAmount")
                if info.get("mint") and amount:
                    holdings[info["mint"]] += float(amount)
        return [Holding(mint=m, amount=a) for m, a in holdings.items()]

    async def get_mint_metadata(self, mint: str) -> MintMeta:
        symbol = None
        try:
            asset = await self._rpc("getAsset", {"id": mint}) or {}
            symbol = ((asset.get("token_info") or {}).get("symbol")
                      or ((asset.get("content") or {}).get("metadata") or {}).get("symbol"))
        except ProviderError:
            pass

        points: list[tuple[datetime, float | None, str | None]] = []
        before, complete = None, False
        for _ in range(config.MINT_HISTORY_PAGE_CAP):
            txs = await self._enhanced(mint, tx_type="SWAP", before=before)
            for tx in txs:
                trader = tx.get("feePayer")
                ts = parse_ts(tx.get("timestamp"))
                if not trader or not ts:
                    continue
                for t in parse_swap_trades(tx, trader):
                    if t.mint == mint:
                        points.append((ts, t.price, t.quote))
            before = txs[-1].get("signature") if txs else None
            if len(txs) < 100 or not before:
                complete = True
                break
        if not points:
            raise ProviderError("no swaps found for mint")

        points.sort(key=lambda p: p[0])
        quotes = [q for _, p, q in points if p is not None and q]
        quote = max(set(quotes), key=quotes.count) if quotes else None
        priced = [(ts, p) for ts, p, q in points if p is not None and q == quote]
        prices = [p for _, p in priced]
        return MintMeta(
            mint=mint, symbol=symbol, first_trade_ts=points[0][0], last_trade_ts=points[-1][0],
            first_price=priced[0][1] if priced else None, last_price=priced[-1][1] if priced else None,
            price_low=min(prices) if prices else None, price_high=max(prices) if prices else None,
            quote=quote, trade_count=len(points), history_complete=complete,
        )

    async def get_mint_creator(self, mint: str) -> str | None:
        page, complete = await self._oldest_signatures(mint)
        if not page or not complete:
            return None
        parsed = await self._parse([page[-1]["signature"]])
        return parsed[0].get("feePayer") if parsed else None

    # --- FundingGraphProvider ----------------------------------------------------------

    async def get_first_funder(self, wallet: str) -> str | None:
        page, complete = await self._oldest_signatures(wallet)
        if not page or not complete:
            return None
        oldest = [s["signature"] for s in reversed(page[-config.FUNDER_SCAN_OLDEST_TXS:])]
        for tx in sorted(await self._parse(oldest), key=lambda t: t.get("timestamp") or 0):
            for nt in tx.get("nativeTransfers") or ():
                if nt.get("toUserAccount") == wallet and (nt.get("amount") or 0) > 0 and nt.get("fromUserAccount"):
                    return nt["fromUserAccount"]
        return None

    async def get_wallets_funded_by(self, funder: str, limit: int) -> list[str]:
        found: list[str] = []
        before = None
        for _ in range(3):
            txs = await self._enhanced(funder, tx_type="TRANSFER", before=before)
            for tx in txs:
                for nt in tx.get("nativeTransfers") or ():
                    to = nt.get("toUserAccount")
                    if nt.get("fromUserAccount") == funder and to and to != funder and to not in found:
                        found.append(to)
                        if len(found) >= limit:
                            return found
            before = txs[-1].get("signature") if txs else None
            if len(txs) < 100 or not before:
                break
        return found

    async def get_mints_created_by(self, wallet: str, limit: int) -> list[str]:
        mints: list[str] = []
        for method, key in (("getAssetsByAuthority", "authorityAddress"), ("getAssetsByCreator", "creatorAddress")):
            params: dict[str, Any] = {key: wallet, "page": 1, "limit": limit}
            if method == "getAssetsByCreator":
                params["onlyVerified"] = False
            res = await self._rpc(method, params)
            for item in (res or {}).get("items") or []:
                if item.get("interface") in FUNGIBLE_INTERFACES and item.get("id") not in mints:
                    mints.append(item["id"])
        return mints[:limit]

    async def aclose(self) -> None:
        await self.http.aclose()
