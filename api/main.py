import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.extract import extract
from core.models import ScanResult
from core.registry import fetch_many
from core.scorer import score_all

from .ratelimit import SlidingWindowRateLimiter
from .security import RequestBodyScrubber, add_security_headers, client_ip


MAX_BODY_BYTES = 200 * 1024
MAX_PACKAGES = 60
SCAN_TIMEOUT_SECONDS = 25
logger = logging.getLogger("slopguard.api")
logger.addFilter(RequestBodyScrubber())
SCAN_LIMITER = SlidingWindowRateLimiter()
SCAN_SEMAPHORE = asyncio.Semaphore(max(1, int(os.getenv("SLOPGUARD_SCAN_CONCURRENCY", "4"))))
BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "bench" / "results" / "summary.json"


class ScanRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_BODY_BYTES)
    kind: Literal["auto", "requirements", "package_json", "python", "javascript", "text"] = "auto"


def _allowed_origins() -> list[str]:
    return [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def harden_requests(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if request.url.path in ("/api/scan", "/api/fix") and content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
        response = JSONResponse({"detail": "request body exceeds the 200 KB limit"}, status_code=413)
        add_security_headers(response.headers, request.url.path)
        return response
    if request.url.path in ("/api/scan", "/api/fix"):
        # Starlette caches this body for downstream validation; it is never logged or persisted.
        if len(await request.body()) > MAX_BODY_BYTES:
            response = JSONResponse({"detail": "request body exceeds the 200 KB limit"}, status_code=413)
            add_security_headers(response.headers, request.url.path)
            return response
        retry_after = await SCAN_LIMITER.check(client_ip(request))
        if retry_after is not None:
            response = JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": str(retry_after)})
            add_security_headers(response.headers, request.url.path)
            return response
    response = await call_next(request)
    add_security_headers(response.headers, request.url.path)
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse({"detail": "invalid request"}, status_code=422)


@app.exception_handler(Exception)
async def internal_error(request: Request, _: Exception) -> JSONResponse:
    logger.error("request failed path=%s", request.url.path)
    response = JSONResponse({"detail": "internal error"}, status_code=500)
    add_security_headers(response.headers, request.url.path)
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _scan(payload: ScanRequest) -> ScanResult:
    refs = extract(payload.content, payload.kind)
    truncated = len(refs) > MAX_PACKAGES
    refs = refs[:MAX_PACKAGES]
    infos = await fetch_many(refs)
    result = score_all(refs, infos)
    result.summary.truncated = truncated
    return result


@app.post("/api/scan", response_model=ScanResult)
async def scan(payload: ScanRequest) -> ScanResult | JSONResponse:
    started = time.monotonic()
    try:
        async with SCAN_SEMAPHORE:
            result = await asyncio.wait_for(_scan(payload), timeout=SCAN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return JSONResponse({"detail": "scan timed out after 25 seconds"}, status_code=504)
    logger.info(
        "scan complete packages=%d verdict=%s duration_ms=%d",
        result.summary.total,
        result.summary.worst_verdict,
        int((time.monotonic() - started) * 1000),
    )
    return result


@app.post("/api/fix")
async def fix(payload: ScanRequest):
    from core.remediate import remediate

    result = await scan(payload)
    if isinstance(result, JSONResponse):
        return result
    fixed = remediate(payload.content, payload.kind, result)
    fixed["summary"] = result.summary.model_dump(mode="json")
    return fixed


@app.get("/api/samples")
async def samples() -> list[dict[str, str]]:
    return [
        {
            "id": "ai-python-imports",
            "title": "AI-style Python imports",
            "kind": "python",
            "content": "import requests\nimport pandas\nimport slopguard_demo_phantom_pkg_93817\n",
        },
        {
            "id": "lookalike-package-json",
            "title": "Lookalike package.json dependency",
            "kind": "package_json",
            "content": '{"dependencies":{"reqeusts":"1.0.0","react":"^18.0.0","lodash":"^4.17.0"}}',
        },
        {
            "id": "clean-requirements",
            "title": "Clean popular requirements",
            "kind": "requirements",
            "content": "requests>=2.31\nfastapi>=0.110\npydantic>=2\n",
        },
    ]


@app.get("/api/benchmark")
async def benchmark() -> JSONResponse:
    try:
        payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return JSONResponse({"detail": "benchmark not generated yet"}, status_code=404)
    except (OSError, json.JSONDecodeError):
        return JSONResponse({"detail": "benchmark unavailable"}, status_code=500)
    return JSONResponse(payload)
