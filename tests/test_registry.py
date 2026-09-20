import asyncio
import functools

import httpx
import pytest

from core.cache import TTLCache
from core.models import Ecosystem, PackageRef
from core import registry


def async_test(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapped


def ref(name: str, ecosystem: Ecosystem = Ecosystem.PYPI) -> PackageRef:
    return PackageRef(name=name, raw=name, ecosystem=ecosystem, source="requirements")


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch) -> TTLCache:
    value = TTLCache(tmp_path)
    monkeypatch.setattr(registry, "_CACHE", value)
    return value


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


@async_test
async def test_pypi_200_metadata_downloads_and_osv(isolated_cache) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 42}})
        return httpx.Response(200, json={"vulns": []})

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("widget"), http_client)
    assert info.exists is True
    assert info.release_count == 2
    assert info.created_at and info.created_at.year == 2021
    assert info.repo_url == "https://github.com/acme/widget"
    assert (info.downloads, info.downloads_period) == (42, "month")
    assert info.latest_version == "2.0"


@async_test
async def test_pypi_404_is_not_found_and_is_cached(isolated_cache) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    async with client(handler) as http_client:
        first = await registry.fetch_package_info(ref("missing"), http_client)
        second = await registry.fetch_package_info(ref("missing"), http_client)
    assert first.exists is False
    assert second.exists is False
    assert calls == 1
    key = registry.cache_key("pypi", "missing", "package-info")
    assert isolated_cache._memory[key][0] - __import__("time").time() < 60 * 60 + 1


@async_test
async def test_npm_scoped_metadata_scripts_and_repo_normalization(isolated_cache) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={
                "time": {"created": "2020-01-01T00:00:00.000Z"},
                "versions": {"1.0.0": {"scripts": {"preinstall": "a", "install": "b", "test": "c"}}},
                "dist-tags": {"latest": "1.0.0"},
                "repository": {"url": "git://github.com/acme/pkg.git"},
            })
        if request.url.host == "api.npmjs.org":
            return httpx.Response(200, json={"downloads": 9})
        return httpx.Response(200, json={"vulns": []})

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("@scope/pkg", Ecosystem.NPM), http_client)
    assert info.exists is True
    assert info.latest_version == "1.0.0"
    assert info.install_scripts == ["preinstall", "install"]
    assert info.repo_url == "https://github.com/acme/pkg"
    assert (info.downloads, info.downloads_period) == (9, "week")
    assert any("%2F" in url or "%2f" in url for url in urls)


@async_test
async def test_npm_404(isolated_cache) -> None:
    async with client(lambda request: httpx.Response(404)) as http_client:
        info = await registry.fetch_package_info(ref("missing", Ecosystem.NPM), http_client)
    assert info.exists is False


@async_test
async def test_retry_429_then_success(isolated_cache, monkeypatch) -> None:
    responses = [429, 200]

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(registry.asyncio, "sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(responses.pop(0), json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 1}})
        return httpx.Response(200, json={"vulns": []})

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("retry"), http_client)
    assert info.exists is True
    assert responses == []


@async_test
async def test_persistent_server_failure_and_timeout_are_unknown(isolated_cache, monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(registry.asyncio, "sleep", no_sleep)
    async with client(lambda request: httpx.Response(500)) as http_client:
        failed = await registry.fetch_package_info(ref("broken"), http_client)
    assert failed.exists is None

    async def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async with client(timeout) as http_client:
        timed_out = await registry.fetch_package_info(ref("slow"), http_client)
    assert timed_out.exists is None
    assert not isolated_cache._memory


@async_test
async def test_osv_malicious_and_auxiliary_failures_do_not_change_existence(isolated_cache) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(500)
        return httpx.Response(200, json={"vulns": [{"id": "MAL-2024-1"}]})

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("affected"), http_client)
    assert info.exists is True
    assert info.downloads is None
    assert info.osv_malicious is True
    assert info.osv_ids == ["MAL-2024-1"]
    assert any(error.startswith("downloads:") for error in info.lookup_errors)


@async_test
async def test_osv_failure_does_not_change_existence(isolated_cache) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi_payload())
        if request.url.host == "pypistats.org":
            return httpx.Response(200, json={"data": {"last_month": 2}})
        return httpx.Response(500)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("osv-down"), http_client)
    assert info.exists is True
    assert any(error.startswith("osv:") for error in info.lookup_errors)


@async_test
async def test_invalid_name_never_makes_a_request(isolated_cache) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with client(handler) as http_client:
        info = await registry.fetch_package_info(ref("bad/name"), http_client)
    assert info.exists is None
    assert calls == 0
