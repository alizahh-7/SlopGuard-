"""Small async-safe, disk-backed TTL cache for registry response data."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


POSITIVE_TTL_SECONDS = 6 * 60 * 60
NOT_FOUND_TTL_SECONDS = 60 * 60


def cache_key(ecosystem: str, name: str, endpoint: str) -> str:
    return hashlib.sha256(f"{ecosystem}:{name}:{endpoint}".encode()).hexdigest()


class TTLCache:
    """A JSON cache that never writes values when caching is disabled."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path(os.getenv("SLOPGUARD_CACHE_DIR", ".cache/slopguard"))
        self.disabled = os.getenv("SLOPGUARD_NO_CACHE") == "1"
        self._memory: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        if self.disabled:
            return None
        async with self._lock:
            now = time.time()
            value = self._memory.get(key)
            if value and value[0] > now:
                return value[1]
            self._memory.pop(key, None)
            path = self.directory / f"{key}.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                expires_at = float(payload["expires_at"])
                if expires_at <= now:
                    path.unlink(missing_ok=True)
                    return None
                self._memory[key] = (expires_at, payload["value"])
                return payload["value"]
            except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self.disabled:
            return
        async with self._lock:
            expires_at = time.time() + ttl_seconds
            self._memory[key] = (expires_at, value)
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{key}.json"
            temporary = self.directory / f".{key}.{os.getpid()}.tmp"
            temporary.write_text(
                json.dumps({"expires_at": expires_at, "value": value}, separators=(",", ":")), encoding="utf-8"
            )
            os.replace(temporary, path)
