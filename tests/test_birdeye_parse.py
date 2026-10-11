import httpx
import pytest
import respx

from crowdcheck.errors import NotSupported
from crowdcheck.http import HttpClient
from crowdcheck.providers.birdeye import BASE, BirdeyeProvider, parse_birdeye_trade


def test_trade_parsing():
    t = parse_birdeye_trade({"base": {"address": "TOK", "ui_change_amount": -12.5, "price": 0.4},
                             "block_unix_time": 1_788_000_000, "tx_hash": "h"}, "W")
    assert (t.mint, t.side, t.token_amount, t.price, t.quote) == ("TOK", "sell", 12.5, 0.4, "USD")
    assert parse_birdeye_trade({"base": {"address": "TOK"}}, "W") is None
    assert parse_birdeye_trade({}, "W") is None


@respx.mock
async def test_mint_metadata_from_price_history():
    respx.get(f"{BASE}/defi/token_overview").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"symbol": "XYZ", "lastTradeUnixTime": 1_788_000_000}}))
    respx.get(f"{BASE}/defi/token_creation_info").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"owner": "Dep", "blockUnixTime": 1_780_000_000}}))
    respx.get(f"{BASE}/defi/history_price").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"items": [{"unixTime": 1_780_100_000, "value": 2.0},
                                            {"unixTime": 1_780_000_000, "value": 1.0},
                                            {"unixTime": 1_780_200_000, "value": 0.5},
                                            {"unixTime": 1_780_300_000}]}}))
    m = await BirdeyeProvider("k", http=HttpClient(max_retries=0)).get_mint_metadata("TOK")
    assert (m.symbol, m.creator, m.first_price, m.last_price, m.price_low, m.price_high) == ("XYZ", "Dep", 1.0, 0.5, 0.5, 2.0)
    assert int(m.last_trade_ts.timestamp()) == 1_788_000_000


async def test_first_activity_not_supported():
    with pytest.raises(NotSupported):
        await BirdeyeProvider("k", http=HttpClient(max_retries=0)).get_wallet_first_activity("W")
