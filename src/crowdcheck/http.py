"""Shared async HTTP client: bounded concurrency, exponential backoff on 429.

API keys travel in URLs (Helius) or headers (Birdeye). Neither is ever put in
an exception message or a log line: errors name only the host and status, and
httpx's own request logging is silenced.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from . import config
from .errors import ProviderError, RateLimited

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, *, concurrency: int = config.HTTP_CONCURRENCY, max_retries: int = config.HTTP_MAX_RETRIES,
                 backoff_base: float = config.HTTP_BACKOFF_BASE_SECONDS, headers: dict[str, str] | None = None,
                 client: httpx.AsyncClient | None = None, sleep=asyncio.sleep):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.client = client or httpx.AsyncClient(timeout=config.HTTP_TIMEOUT_SECONDS, headers=headers)
        self._sleep = sleep
        self.requests = 0

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                return float(retry_after)
        return self.backoff_base * (2 ** attempt) * (1 + random.random() * 0.1)

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        host = httpx.URL(url).host
        last_status: int | None = None
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                async with self.semaphore:
                    self.requests += 1
                    response = await self.client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_status = None
                if attempt == self.max_retries:
                    raise ProviderError(f"{host} unreachable ({type(exc).__name__})") from None
            else:
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError:
                        raise ProviderError(f"{host} returned non-JSON") from None
                last_status = response.status_code
                if response.status_code in (401, 403):
                    raise ProviderError(f"{host} rejected the API key (HTTP {response.status_code})")
                if response.status_code not in RETRY_STATUS:
                    raise ProviderError(f"{host} returned HTTP {response.status_code}")
                if attempt == self.max_retries:
                    break
            await self._sleep(self._delay(attempt, response))
        if last_status == 429:
            raise RateLimited(f"{host} rate limited after {self.max_retries} retries")
        raise ProviderError(f"{host} failed after {self.max_retries} retries (HTTP {last_status})")

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None:
        await self.client.aclose()
