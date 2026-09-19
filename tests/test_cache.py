import asyncio
import functools

import pytest

from core.cache import NOT_FOUND_TTL_SECONDS, POSITIVE_TTL_SECONDS, TTLCache, cache_key


def async_test(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapped


@async_test
async def test_cache_round_trip_and_key(tmp_path) -> None:
    cache = TTLCache(tmp_path)
    key = cache_key("pypi", "requests", "registry")
    await cache.set(key, {"exists": True}, POSITIVE_TTL_SECONDS)

    assert len(key) == 64
    assert await cache.get(key) == {"exists": True}
    assert list(tmp_path.glob("*.json"))


@async_test
async def test_404_ttl_is_shorter_and_expired_values_are_removed(tmp_path, monkeypatch) -> None:
    cache = TTLCache(tmp_path)
    key = cache_key("npm", "missing", "registry")
    now = 1_000.0
    monkeypatch.setattr("core.cache.time.time", lambda: now)
    await cache.set(key, {"exists": False}, NOT_FOUND_TTL_SECONDS)
    assert cache._memory[key][0] - now == NOT_FOUND_TTL_SECONDS
    monkeypatch.setattr("core.cache.time.time", lambda: now + NOT_FOUND_TTL_SECONDS + 1)
    assert await cache.get(key) is None


@async_test
async def test_cache_can_be_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SLOPGUARD_NO_CACHE", "1")
    cache = TTLCache(tmp_path)
    await cache.set("key", {"value": 1}, 10)
    assert await cache.get("key") is None
    assert not list(tmp_path.iterdir())
