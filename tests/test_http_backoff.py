import httpx
import pytest
import respx

from crowdcheck.errors import ProviderError, RateLimited
from crowdcheck.http import HttpClient

URL = "https://api.example.test/v0/thing"


def client(sleeps):
    async def fake_sleep(s):
        sleeps.append(s)
    return HttpClient(max_retries=3, backoff_base=1.0, sleep=fake_sleep)


@respx.mock
async def test_retries_429_with_exponential_backoff_then_succeeds():
    sleeps = []
    route = respx.get(URL).mock(side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200, json={"ok": 1})])
    assert await client(sleeps).get(URL) == {"ok": 1}
    assert route.call_count == 3
    assert 1.0 <= sleeps[0] < 1.2 and 2.0 <= sleeps[1] < 2.4    # base * 2^attempt, small jitter


@respx.mock
async def test_gives_up_with_rate_limited():
    sleeps = []
    respx.get(URL).mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimited):
        await client(sleeps).get(URL)
    assert len(sleeps) == 3


@respx.mock
async def test_honours_retry_after():
    sleeps = []
    respx.get(URL).mock(side_effect=[httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, json=[])])
    await client(sleeps).get(URL)
    assert sleeps == [7.0]


@respx.mock
async def test_errors_never_contain_the_api_key():
    respx.get(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(ProviderError) as exc:
        await client([]).get(URL, params={"api-key": "SECRET123"})
    assert "SECRET123" not in str(exc.value) and "api.example.test" in str(exc.value)


@respx.mock
async def test_non_retryable_status_fails_fast():
    route = respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(ProviderError):
        await client([]).get(URL)
    assert route.call_count == 1
