"""HTTP-boundary helpers that avoid retaining or emitting request content."""

import logging
import os

from fastapi import Request


def client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"


def add_security_headers(headers, path: str) -> None:
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"
    headers["Content-Security-Policy"] = "default-src 'none'"
    if path == "/api/scan":
        headers["Cache-Control"] = "no-store"


class RequestBodyScrubber(logging.Filter):
    """Prevents accidental request-body attributes from reaching application logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        for attribute in ("body", "content", "request_body"):
            if hasattr(record, attribute):
                setattr(record, attribute, "[scrubbed]")
        return True
