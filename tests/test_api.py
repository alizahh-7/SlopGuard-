import importlib
import logging

from fastapi.testclient import TestClient

from api import main
from api.ratelimit import SlidingWindowRateLimiter
from core.models import Ecosystem, PackageInfo, PackageRef


def package_ref(name: str) -> PackageRef:
    return PackageRef(name=name, raw=name, ecosystem=Ecosystem.PYPI, source="requirements")


def install_registry_mock(monkeypatch) -> None:
    async def fake_fetch_many(refs):
        return {
            (ref.ecosystem.value, ref.name): PackageInfo(
                name=ref.name,
                ecosystem=ref.ecosystem,
                exists=True,
                downloads=1_000_000,
                repo_url="https://github.com/example/source",
                release_count=5,
            )
            for ref in refs
        }

    monkeypatch.setattr(main, "fetch_many", fake_fetch_many)


def test_valid_scan_and_security_headers(monkeypatch) -> None:
    install_registry_mock(monkeypatch)
    monkeypatch.setattr(main, "SCAN_LIMITER", SlidingWindowRateLimiter())
    with TestClient(main.app) as client:
        response = client.post("/api/scan", json={"content": "requests==2.31", "kind": "requirements"})
    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 1
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'none'"
    assert response.headers["cache-control"] == "no-store"


def test_invalid_request_and_oversize_are_safe(monkeypatch) -> None:
    monkeypatch.setattr(main, "SCAN_LIMITER", SlidingWindowRateLimiter())
    with TestClient(main.app) as client:
        empty = client.post("/api/scan", json={"content": ""})
        invalid_kind = client.post("/api/scan", json={"content": "requests", "kind": "shell"})
        oversize = client.post("/api/scan", json={"content": "x" * (main.MAX_BODY_BYTES + 1)})
    assert empty.status_code == 422
    assert invalid_kind.status_code == 422
    assert oversize.status_code == 413
    assert "x" * 20 not in oversize.text


def test_truncation_and_logs_do_not_contain_content(monkeypatch, caplog) -> None:
    refs = [package_ref(f"package{i}") for i in range(61)]
    monkeypatch.setattr(main, "extract", lambda content, kind: refs)
    install_registry_mock(monkeypatch)
    monkeypatch.setattr(main, "SCAN_LIMITER", SlidingWindowRateLimiter())
    secret = "DO_NOT_LOG_THIS_PRIVATE_SNIPPET"
    caplog.set_level(logging.INFO, logger="slopguard.api")
    with TestClient(main.app) as client:
        response = client.post("/api/scan", json={"content": secret})
    assert response.status_code == 200
    assert response.json()["summary"]["truncated"] is True
    assert response.json()["summary"]["total"] == 60
    assert secret not in caplog.text
    assert secret not in response.text


def test_rate_limit_returns_retry_after(monkeypatch) -> None:
    install_registry_mock(monkeypatch)
    monkeypatch.setattr(main, "SCAN_LIMITER", SlidingWindowRateLimiter(minute_limit=2, hour_limit=200))
    with TestClient(main.app) as client:
        assert client.post("/api/scan", json={"content": "requests"}).status_code == 200
        assert client.post("/api/scan", json={"content": "requests"}).status_code == 200
        limited = client.post("/api/scan", json={"content": "requests"})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_samples_shape_and_benchmark_states(monkeypatch, tmp_path) -> None:
    path = tmp_path / "summary.json"
    monkeypatch.setattr(main, "BENCHMARK_PATH", path)
    with TestClient(main.app) as client:
        samples = client.get("/api/samples")
        missing = client.get("/api/benchmark")
    assert samples.status_code == 200
    assert len(samples.json()) == 3
    assert all(set(item) == {"id", "title", "kind", "content"} for item in samples.json())
    assert missing.status_code == 404
    path.write_text('{"packages": 3}', encoding="utf-8")
    with TestClient(main.app) as client:
        ready = client.get("/api/benchmark")
    assert ready.status_code == 200
    assert ready.json() == {"packages": 3}


def test_cors_only_allows_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://allowed.example")
    reloaded = importlib.reload(main)
    try:
        with TestClient(reloaded.app) as client:
            allowed = client.get("/api/health", headers={"Origin": "https://allowed.example"})
            denied = client.get("/api/health", headers={"Origin": "https://denied.example"})
        assert allowed.headers["access-control-allow-origin"] == "https://allowed.example"
        assert "access-control-allow-origin" not in denied.headers
    finally:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        importlib.reload(main)
