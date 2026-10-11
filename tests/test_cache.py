from crowdcheck.cache import Cache


def test_roundtrip_and_ttl(tmp_path):
    c = Cache(tmp_path / "x" / "c.sqlite")       # parent dir is created on first run
    c.set("ns", "k", {"a": [1, 2]}, now=1000)
    assert c.get("ns", "k", ttl_seconds=60, now=1050) == {"a": [1, 2]}
    assert c.get("ns", "k", ttl_seconds=60, now=1061) is Cache.MISS
    assert c.get("ns", "other", ttl_seconds=60) is Cache.MISS


def test_none_is_a_valid_cached_value(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.set("ns", "k", None, now=0)
    assert c.get("ns", "k", ttl_seconds=10, now=1) is None
