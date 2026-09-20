"""Recorded OSV fixtures: current-version MAL vs historical-only MAL."""

import asyncio
import functools
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from core import registry
from core.cache import TTLCache
from core.models import Ecosystem, PackageRef
from core.scorer import score_package
from core.signals import SignalContext

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "osv"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def async_test(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapped


def ref(name: str, ecosystem: Ecosystem = Ecosystem.PYPI) -> PackageRef:
    return PackageRef(name=name, raw=name, ecosystem=ecosystem, source="requirements")


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def pypi_payload() -> dict:
    return {
        "info": {"version": "2.0", "project_urls": {"Source Code": "https://github.com/acme/widget"}},
        "releases": {
            "1.0": [{"upload_time_iso_8601": "2022-02-01T00:00:00Z"}],
            "2.0": [{"upload_time_iso_8601": "2021-01-01T00:00:00Z"}],
            "empty": [],
        },
    }


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch) -> TTLCache:
    value = TTLCache(tmp_path)
    monkeypatch.setattr(registry, "_CACHE", value)
    return value


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _osv_body(request: httpx.Request) -> dict:
    return json.loads(request.content) if request.content else {}


def _pypi_without_version() -> dict:
    payload = pypi_payload()
    payload["info"] = {key: value for key, value in payload["info"].items() if key != "version"}
    return payload


@async_test
async def test_advisory_affecting_latest_is_block(isolated_cache) -> None:
    unversioned = _load("unversioned_malicious.json")
    versioned = _load("versioned_malicious.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 10}})
        body = _osv_body(request)
        if "version" in body:
            return httpx.Response(200, json=versioned)
        return httpx.Response(200, json=unversioned)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("affected"), http_client)
    verdict = score_package(ref("affected"), info, SignalContext(NOW))
    assert info.osv_malicious is True
    assert info.osv_ids == ["MAL-2024-axios", "GHSA-0000-0000-0000"]
    assert (verdict.verdict, verdict.risk) == ("BLOCK", 100)


@async_test
async def test_advisory_only_on_old_versions_is_historical(isolated_cache) -> None:
    unversioned = _load("unversioned_malicious.json")
    versioned = _load("versioned_clean.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 10}})
        body = _osv_body(request)
        if "version" in body:
            return httpx.Response(200, json=versioned)
        return httpx.Response(200, json=unversioned)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("historical"), http_client)
    verdict = score_package(ref("historical"), info, SignalContext(NOW))
    assert info.osv_malicious is False
    assert "MAL-2024-axios" in info.osv_ids
    assert verdict.verdict != "BLOCK"
    assert any(finding.signal == "historical_advisory" for finding in verdict.findings)


@async_test
async def test_no_advisory_is_unchanged(isolated_cache) -> None:
    empty = _load("empty.json")
    calls = {"osv": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 10}})
        calls["osv"] += 1
        return httpx.Response(200, json=empty)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("clean"), http_client)
    verdict = score_package(ref("clean"), info, SignalContext(NOW))
    assert info.osv_malicious is False
    assert info.osv_ids == []
    assert calls["osv"] == 1
    assert verdict.verdict != "BLOCK"
    assert "historical_advisory" not in {finding.signal for finding in verdict.findings}
    assert "malicious_advisory" not in {finding.signal for finding in verdict.findings}


@async_test
async def test_versioned_query_failure_is_unknown(isolated_cache, monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(registry.asyncio, "sleep", no_sleep)
    unversioned = _load("unversioned_malicious.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 10}})
        if "version" in _osv_body(request):
            return httpx.Response(500)
        return httpx.Response(200, json=unversioned)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("osv-flaky"), http_client)
    verdict = score_package(ref("osv-flaky"), info, SignalContext(NOW))
    assert info.osv_check_failed is True
    assert info.osv_malicious is False
    assert verdict.verdict == "UNKNOWN"
    assert verdict.findings[0].message == "An advisory exists but could not be confirmed against the latest version"


@async_test
async def test_unknown_latest_version_does_not_block(isolated_cache) -> None:
    unversioned = _load("unversioned_malicious.json")
    calls = {"osv": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=_pypi_without_version())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 10}})
        calls["osv"] += 1
        return httpx.Response(200, json=unversioned)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("no-latest"), http_client)
    verdict = score_package(ref("no-latest"), info, SignalContext(NOW))
    assert info.latest_version is None
    assert info.osv_malicious is False
    assert calls["osv"] == 1
    assert verdict.verdict != "BLOCK"


@async_test
async def test_osv_queries_are_cached(isolated_cache) -> None:
    unversioned = _load("unversioned_malicious.json")
    versioned = _load("versioned_clean.json")
    calls = {"osv": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 10}})
        calls["osv"] += 1
        if "version" in _osv_body(request):
            return httpx.Response(200, json=versioned)
        return httpx.Response(200, json=unversioned)

    async with client(handler) as http_client:
        first = await registry.fetch_package_info(ref("cached"), http_client)
        second = await registry.fetch_package_info(ref("cached"), http_client)
    assert first.osv_ids == second.osv_ids
    assert calls["osv"] == 2
    assert await isolated_cache.get(registry.cache_key("pypi", "cached", "osv")) == {"ids": ["MAL-2024-axios", "GHSA-0000-0000-0000"]}
    assert await isolated_cache.get(registry.cache_key("pypi", "cached", "osv:2.0")) == {"ids": ["GHSA-0000-0000-0000"]}
