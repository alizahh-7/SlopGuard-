"""Read-only, fixed-host registry lookups for validated package references."""

import asyncio
import random
import re
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .cache import NOT_FOUND_TTL_SECONDS, POSITIVE_TTL_SECONDS, TTLCache, cache_key
from .models import Ecosystem, PackageInfo, PackageRef


_USER_AGENT = "slopguard/0.1 (security research; read-only)"
_PYPI_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
_NPM_PATTERN = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*|[a-z0-9][a-z0-9._-]*)$")
_HOST_LIMITS: defaultdict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(2))
_CACHE = TTLCache()


def _valid_ref(ref: PackageRef) -> bool:
    pattern = _PYPI_PATTERN if ref.ecosystem is Ecosystem.PYPI else _NPM_PATTERN
    return bool(pattern.fullmatch(ref.name))


def _url(host: str, path: str, name: str) -> str:
    return f"https://{host}/{path}/{quote(name, safe='')}"


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After", "")
    try:
        return min(8.0, max(0.0, float(value)))
    except ValueError:
        try:
            return min(8.0, max(0.0, (parsedate_to_datetime(value) - datetime.now(parsedate_to_datetime(value).tzinfo)).total_seconds()))
        except (TypeError, ValueError):
            return min(8.0, 0.25 * (2**attempt) + random.uniform(0, 0.25))


async def _request(
    client: httpx.AsyncClient, method: str, url: str, *, payload: dict[str, Any] | None = None
) -> tuple[httpx.Response | None, str | None]:
    """Return a response or a non-sensitive failure message after bounded retries."""
    host = urlparse(url).netloc
    for attempt in range(4):
        try:
            async with _HOST_LIMITS[host]:
                response = await client.request(method, url, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt == 3:
                return None, f"{host}: request failed ({exc.__class__.__name__})"
            await asyncio.sleep(min(8.0, 0.25 * (2**attempt) + random.uniform(0, 0.25)))
            continue
        if response.status_code == 404:
            return response, None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 3:
                return None, f"{host}: HTTP {response.status_code}"
            await asyncio.sleep(_retry_after(response, attempt))
            continue
        if 200 <= response.status_code < 300:
            return response, None
        return None, f"{host}: HTTP {response.status_code}"
    return None, f"{host}: request failed"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pypi_repo(info: dict[str, Any]) -> str | None:
    project_urls = info.get("project_urls")
    if isinstance(project_urls, dict):
        wanted = ("source", "source code", "repository", "code", "github", "homepage")
        lowered = {str(key).lower(): value for key, value in project_urls.items()}
        for key in wanted:
            value = lowered.get(key)
            if isinstance(value, str) and value:
                return value
    homepage = info.get("home_page")
    if isinstance(homepage, str):
        host = urlparse(homepage).netloc.lower()
        if any(host == site or host.endswith(f".{site}") for site in ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")):
            return homepage
    return None


def _npm_repo(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("url")
    if not isinstance(value, str) or not value:
        return None
    value = value.removeprefix("git+")
    if value.startswith("git://"):
        value = "https://" + value[len("git://"):]
    if value.endswith(".git"):
        value = value[:-4]
    return value


def _pypi_info(ref: PackageRef, data: dict[str, Any]) -> PackageInfo:
    releases = data.get("releases") if isinstance(data.get("releases"), dict) else {}
    dates = [
        parsed
        for files in releases.values()
        if isinstance(files, list)
        for item in files
        if isinstance(item, dict)
        for parsed in [_parse_datetime(item.get("upload_time_iso_8601"))]
        if parsed is not None
    ]
    project = data.get("info") if isinstance(data.get("info"), dict) else {}
    version = project.get("version")
    return PackageInfo(
        name=ref.name,
        ecosystem=ref.ecosystem,
        exists=True,
        created_at=min(dates) if dates else None,
        release_count=sum(1 for files in releases.values() if isinstance(files, list) and files),
        repo_url=_pypi_repo(project),
        latest_version=version if isinstance(version, str) and version else None,
    )


def _npm_info(ref: PackageRef, data: dict[str, Any]) -> PackageInfo:
    versions = data.get("versions") if isinstance(data.get("versions"), dict) else {}
    latest = data.get("dist-tags", {}).get("latest") if isinstance(data.get("dist-tags"), dict) else None
    latest_info = versions.get(latest, {}) if isinstance(latest, str) else {}
    scripts = latest_info.get("scripts", {}) if isinstance(latest_info, dict) else {}
    install_scripts = [name for name in ("preinstall", "install", "postinstall") if isinstance(scripts, dict) and name in scripts]
    time_data = data.get("time") if isinstance(data.get("time"), dict) else {}
    return PackageInfo(
        name=ref.name,
        ecosystem=ref.ecosystem,
        exists=True,
        created_at=_parse_datetime(time_data.get("created")),
        release_count=len(versions),
        repo_url=_npm_repo(data.get("repository")),
        install_scripts=install_scripts,
        latest_version=latest if isinstance(latest, str) and latest else None,
    )


def _osv_payload(ref: PackageRef, version: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"package": {"name": ref.name, "ecosystem": "PyPI" if ref.ecosystem is Ecosystem.PYPI else "npm"}}
    if version is not None:
        payload["version"] = version
    return payload


async def _osv_query(client: httpx.AsyncClient, ref: PackageRef, version: str | None = None) -> tuple[list[str] | None, str | None]:
    endpoint = "osv" if version is None else f"osv:{version}"
    key = cache_key(ref.ecosystem.value, ref.name, endpoint)
    cached = await _CACHE.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("ids"), list):
        return [item for item in cached["ids"] if isinstance(item, str)], None
    response, error = await _request(client, "POST", "https://api.osv.dev/v1/query", payload=_osv_payload(ref, version))
    if error:
        return None, error
    if response is None:
        return None, "api.osv.dev: request failed"
    if response.status_code == 404:
        return None, "api.osv.dev: HTTP 404"
    try:
        vulnerabilities = response.json().get("vulns", [])
        ids = [item["id"] for item in vulnerabilities if isinstance(item, dict) and isinstance(item.get("id"), str)]
    except ValueError:
        return None, "osv: invalid response"
    await _CACHE.set(key, {"ids": ids}, POSITIVE_TTL_SECONDS)
    return ids, None


async def _supplement(info: PackageInfo, ref: PackageRef, client: httpx.AsyncClient) -> PackageInfo:
    encoded_name = quote(ref.name, safe="")
    if ref.ecosystem is Ecosystem.PYPI:
        downloads_url = f"https://pypistats.org/api/packages/{encoded_name}/recent"
    else:
        downloads_url = f"https://api.npmjs.org/downloads/point/last-week/{encoded_name}"
    downloads_result, osv_result = await asyncio.gather(
        _request(client, "GET", downloads_url), _osv_query(client, ref), return_exceptions=True
    )
    errors = list(info.lookup_errors)
    if isinstance(downloads_result, Exception):
        errors.append("downloads: unexpected failure")
    else:
        response, error = downloads_result
        if error:
            errors.append(f"downloads: {error}")
        elif response and response.status_code != 404:
            try:
                payload = response.json()
                value = payload.get("data", {}).get("last_month") if ref.ecosystem is Ecosystem.PYPI else payload.get("downloads")
                if isinstance(value, int):
                    info.downloads = value
                    info.downloads_period = "month" if ref.ecosystem is Ecosystem.PYPI else "week"
                else:
                    errors.append("downloads: invalid response")
            except ValueError:
                errors.append("downloads: invalid response")
        else:
            errors.append("downloads: HTTP 404")
    if isinstance(osv_result, Exception):
        errors.append("osv: unexpected failure")
    else:
        ids, error = osv_result
        if error:
            errors.append(f"osv: {error}")
        else:
            info.osv_ids = ids or []
            has_malicious = any(identifier.startswith("MAL-") for identifier in info.osv_ids)
            if has_malicious and info.latest_version:
                versioned_ids, versioned_error = await _osv_query(client, ref, info.latest_version)
                if versioned_error:
                    info.osv_check_failed = True
                    info.osv_malicious = False
                    errors.append(f"osv: {versioned_error}")
                else:
                    info.osv_malicious = any(identifier.startswith("MAL-") for identifier in (versioned_ids or []))
            else:
                info.osv_malicious = False
    info.lookup_errors = errors
    return info


async def fetch_package_info(ref: PackageRef, client: httpx.AsyncClient | None = None) -> PackageInfo:
    """Fetch public metadata without ever treating a request failure as absence."""
    if not _valid_ref(ref):
        return PackageInfo(name=ref.name, ecosystem=ref.ecosystem, lookup_errors=["invalid package name"])
    key = cache_key(ref.ecosystem.value, ref.name, "package-info")
    cached = await _CACHE.get(key)
    if isinstance(cached, dict):
        return PackageInfo.model_validate(cached)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(5.0), headers={"User-Agent": _USER_AGENT})
    try:
        if ref.ecosystem is Ecosystem.PYPI:
            url = f"https://pypi.org/pypi/{quote(ref.name, safe='')}/json"
        else:
            url = f"https://registry.npmjs.org/{quote(ref.name, safe='')}"
        response, error = await _request(client, "GET", url)
        if error:
            return PackageInfo(name=ref.name, ecosystem=ref.ecosystem, lookup_errors=[f"registry: {error}"])
        if response is None:
            return PackageInfo(name=ref.name, ecosystem=ref.ecosystem, lookup_errors=["registry: request failed"])
        if response.status_code == 404:
            info = PackageInfo(name=ref.name, ecosystem=ref.ecosystem, exists=False)
            await _CACHE.set(key, info.model_dump(mode="json"), NOT_FOUND_TTL_SECONDS)
            return info
        try:
            payload = response.json()
        except ValueError:
            return PackageInfo(name=ref.name, ecosystem=ref.ecosystem, lookup_errors=["registry: invalid response"])
        if not isinstance(payload, dict):
            return PackageInfo(name=ref.name, ecosystem=ref.ecosystem, lookup_errors=["registry: invalid response"])
        info = _pypi_info(ref, payload) if ref.ecosystem is Ecosystem.PYPI else _npm_info(ref, payload)
        info = await _supplement(info, ref, client)
        if not info.lookup_errors:
            await _CACHE.set(key, info.model_dump(mode="json"), POSITIVE_TTL_SECONDS)
        return info
    finally:
        if owns_client:
            await client.aclose()


async def fetch_many(refs: list[PackageRef], concurrency: int = 10) -> dict[tuple[str, str], PackageInfo]:
    """Fetch a batch with bounded concurrency; a single lookup never aborts the batch."""
    limit = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), headers={"User-Agent": _USER_AGENT}) as client:
        async def one(ref: PackageRef) -> PackageInfo:
            async with limit:
                return await fetch_package_info(ref, client)

        outcomes = await asyncio.gather(*(one(ref) for ref in refs), return_exceptions=True)
    result: dict[tuple[str, str], PackageInfo] = {}
    for ref, outcome in zip(refs, outcomes):
        if isinstance(outcome, Exception):
            outcome = PackageInfo(name=ref.name, ecosystem=ref.ecosystem, lookup_errors=["registry: unexpected failure"])
        result[(ref.ecosystem.value, ref.name)] = outcome
    return result
