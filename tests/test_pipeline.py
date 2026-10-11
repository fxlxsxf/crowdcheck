import pytest

from conftest import FIXTURES, NOW, TARGET
from crowdcheck.cache import Cache
from crowdcheck.errors import CrowdcheckError, RateLimited
from crowdcheck.models import MetricName as M
from crowdcheck.pipeline import RunOptions, run, walk_funding_graph
from crowdcheck.providers.cached import CachedProvider
from crowdcheck.providers.mock import MockProvider


async def report_for(provider, **kw):
    return await run(provider, TARGET, RunOptions(now=NOW, **kw))


async def test_basic_end_to_end_known_answers(basic):
    r = await report_for(basic, top_n=5)
    assert r.symbol == "ROOM" and r.holders_found == 5

    tr = r.result(M.TRACK_RECORD).raw
    # prior mints A (2 buyers), B, C, D; D has no metadata; only A lived 30 days and is still active
    assert (tr["prior_mints"], tr["resolved"], tr["survived"]) == (4, 3, 1)

    wa = r.result(M.WALLET_AGE).raw
    # W5 has no first activity; W1 and W4 are under 24h, W2 under 7d, W3 old
    assert (wa["resolved"], wa["under_24h"], wa["under_7d"]) == (4, 2, 3)

    dp = r.result(M.DEPLOYER).raw
    # Creator1 <- Funder1 -> Sib1, Sib2; mints P1 (-98%, 10d), P2 (-95%, 40d), P3 (no prices)
    assert dp["linked_mints"] == 3 and dp["median_outcome_pct"] == -96.5 and dp["longest_survivor_days"] == 40
    assert dp["wallets_walked"] == 4

    ov = r.result(M.OVERLAP).raw
    assert [t["mint"] for t in ov["top"]] == ["MintX", "MintY", "MintZ"] and ov["holding_all_top"] == 2

    ht = r.result(M.HOLD_TIME).raw
    # closed: 30s, 100s, 1200s, 45s (W3 sold 9.6 of 10, above the 95% line)
    assert ht["median_seconds"] == 72.5 and ht["under_fast"] == 2

    ex = r.result(M.EXIT_PERCENTILE).raw
    assert ex["exits"] == 3 and round(ex["median_percentile"], 2) == 66.67

    assert r.score.total is not None and not r.score.too_thin
    assert "1 prior mint metadata calls failed" in " ".join(r.notes)


async def test_never_fetches_the_same_wallet_twice(basic, basic_mock):
    await report_for(basic, top_n=5)
    assert max(basic_mock.calls.values()) == 1
    # Creator1 metadata comes from target metadata; mint metadata asked once each even though
    # A is bought by two wallets.
    assert basic_mock.calls["get_mint_metadata:MintA"] == 1


async def test_disk_cache_survives_between_runs(tmp_path, basic_mock):
    db = tmp_path / "c.sqlite"
    await report_for(CachedProvider(basic_mock, Cache(db)), top_n=5)
    first = sum(basic_mock.calls.values())
    second_mock = MockProvider(FIXTURES / "basic")
    await report_for(CachedProvider(second_mock, Cache(db)), top_n=5)
    assert first > 0
    # only failing calls (MintD metadata) are retried; everything else came from disk
    assert dict(second_mock.calls) == {"get_mint_metadata:MintD": 1}


async def test_holder_list_shorter_than_n(basic):
    r = await report_for(basic, top_n=100)
    assert r.holders_found == 5
    assert "only 5 holders found, fewer than the 100 requested" in r.notes


async def test_rate_limited_wallets_become_not_visible():
    mock = MockProvider(FIXTURES / "basic", fail={
        "get_wallet_dex_trades:*": RateLimited("api rate limited after 5 retries"),
        "get_wallet_first_activity:*": RateLimited("api rate limited after 5 retries"),
    })
    r = await report_for(CachedProvider(mock, None), top_n=5)
    assert not r.result(M.TRACK_RECORD).visible
    assert not r.result(M.WALLET_AGE).visible
    assert not r.result(M.HOLD_TIME).visible
    assert not r.result(M.EXIT_PERCENTILE).visible
    assert r.score.total is None and r.score.too_thin
    assert any("trade history calls failed (api rate limited" in n for n in r.notes)


async def test_partial_fields_do_not_crash():
    r = await report_for(CachedProvider(MockProvider(FIXTURES / "partial_fields"), None), top_n=10)
    assert r.holders_found == 2
    assert r.result(M.HOLD_TIME).raw["median_seconds"] == 120      # the one complete round trip
    assert r.result(M.EXIT_PERCENTILE).reason == "no priced exits"
    assert r.result(M.WALLET_AGE).reason == "no first activity resolved"
    assert r.result(M.TRACK_RECORD).reason == "no prior mint lifespan resolved"
    assert r.result(M.DEPLOYER).reason == "mint creator not resolved"
    assert r.score.total is None


async def test_funding_graph_can_be_disabled(basic, basic_mock):
    r = await report_for(basic, top_n=5, funding_graph=False)
    assert r.result(M.DEPLOYER).reason == "funding graph disabled"
    assert not any(k.startswith("get_first_funder") for k in basic_mock.calls)


async def test_hub_funder_is_not_expanded(basic):
    basic.inner.funding["funded_by"]["Funder1"] = [f"X{i}" for i in range(60)]
    graph, notes = await walk_funding_graph(basic, "Creator1", target_mint=TARGET, max_wallets=50)
    assert graph.wallets == ["Creator1", "Funder1"] and graph.truncated and notes


async def test_no_holders_is_an_error(basic):
    with pytest.raises(CrowdcheckError):
        await run(basic, "UnknownMint111111111111111111111111111111", RunOptions(now=NOW))
