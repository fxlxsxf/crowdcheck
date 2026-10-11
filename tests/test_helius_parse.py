"""Helius parsing against hand-written enhanced-transaction payloads. No network."""

import httpx
import respx

from crowdcheck.http import HttpClient
from crowdcheck.providers.helius import WSOL, HeliusProvider, parse_swap_trades

W = "Wallet1"


def tx(token=(), native=(), ts=1_788_000_000, sig="s1", fee_payer=W):
    return {"signature": sig, "timestamp": ts, "feePayer": fee_payer,
            "tokenTransfers": list(token), "nativeTransfers": list(native)}


def tt(mint, amount, frm, to):
    return {"mint": mint, "tokenAmount": amount, "fromUserAccount": frm, "toUserAccount": to}


def nt(lamports, frm, to):
    return {"amount": lamports, "fromUserAccount": frm, "toUserAccount": to}


def test_buy_with_native_sol():
    (t,) = parse_swap_trades(tx(token=[tt("TOK", 1000, "Pool", W)], native=[nt(2_000_000_000, W, "Pool")]), W)
    assert (t.side, t.token_amount, t.price, t.quote) == ("buy", 1000, 0.002, "SOL")


def test_sell_for_wsol():
    (t,) = parse_swap_trades(tx(token=[tt("TOK", 500, W, "Pool"), tt(WSOL, 1.5, "Pool", W)]), W)
    assert (t.side, t.price, t.quote) == ("sell", 0.003, "SOL")


def test_usdc_quote_preferred():
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    (t,) = parse_swap_trades(tx(token=[tt("TOK", 10, "Pool", W), tt(usdc, 25, W, "Pool")]), W)
    assert (t.price, t.quote) == (2.5, "USD")


def test_token_to_token_swap_has_no_price():
    trades = parse_swap_trades(tx(token=[tt("A", 10, W, "Pool"), tt("B", 20, "Pool", W)]), W)
    assert {t.mint: t.side for t in trades} == {"A": "sell", "B": "buy"}
    assert all(t.price is None for t in trades)


def test_missing_fields_are_skipped():
    assert parse_swap_trades({"signature": "x"}, W) == []
    assert parse_swap_trades(tx(token=[{"mint": "TOK"}, {"tokenAmount": 3}]), W) == []


@respx.mock
async def test_first_activity_and_creator_from_rpc():
    sigs = [{"signature": f"s{i}", "blockTime": 1_788_000_000 - i} for i in range(3)]
    respx.post("https://mainnet.helius-rpc.com/").mock(return_value=httpx.Response(200, json={"result": sigs}))
    respx.post("https://api.helius.xyz/v0/transactions").mock(
        return_value=httpx.Response(200, json=[{"feePayer": "Deployer1"}]))
    p = HeliusProvider("k", http=HttpClient(max_retries=0))
    first = await p.get_wallet_first_activity("W")
    assert int(first.timestamp()) == 1_788_000_000 - 2
    assert await p.get_mint_creator("M") == "Deployer1"


@respx.mock
async def test_holders_drop_non_wallet_owners():
    def rpc(request):
        import json
        body = json.loads(request.content)
        m = body["method"]
        if m == "getTokenSupply":
            return httpx.Response(200, json={"result": {"value": {"decimals": 2, "uiAmount": 100.0}}})
        if m == "getTokenAccounts":
            return httpx.Response(200, json={"result": {"token_accounts": [
                {"owner": "Alice", "amount": 5000}, {"owner": "PoolPda", "amount": 4000}, {"owner": "Bob", "amount": 500},
                {"owner": "Alice", "amount": 100}]}})
        if m == "getMultipleAccounts":
            owners = {"Alice": "11111111111111111111111111111111", "Bob": "11111111111111111111111111111111"}
            return httpx.Response(200, json={"result": {"value": [
                {"owner": owners[a]} if a in owners else None for a in body["params"][0]]}})
        return httpx.Response(400)
    respx.post("https://mainnet.helius-rpc.com/").mock(side_effect=rpc)
    p = HeliusProvider("k", http=HttpClient(max_retries=0))
    hs = await p.get_top_holders("M", 10)
    assert [(h.wallet, h.amount) for h in hs] == [("Alice", 51.0), ("Bob", 5.0)]
    assert hs[0].share_of_supply == 0.51
