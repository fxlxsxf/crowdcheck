import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crowdcheck.cache import Cache
from crowdcheck.providers.cached import CachedProvider
from crowdcheck.providers.mock import MockProvider

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
TARGET = "TargetMint1111111111111111111111111111111"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any test that tries to open a real connection fails loudly."""
    def guard(*args, **kwargs):
        raise RuntimeError("tests must not touch the network")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def basic_mock():
    return MockProvider(FIXTURES / "basic")


@pytest.fixture
def basic(basic_mock):
    return CachedProvider(basic_mock, Cache(":memory:"))
