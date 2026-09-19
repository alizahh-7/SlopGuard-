"""In-process sliding-window limits for the public scan endpoint."""

import asyncio
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, minute_limit: int = 20, hour_limit: int = 200) -> None:
        self.minute_limit = minute_limit
        self.hour_limit = hour_limit
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, client_ip: str) -> int | None:
        """Record a request and return a whole-second retry delay when limited."""
        now = time.monotonic()
        async with self._lock:
            requests = self._requests[client_ip]
            while requests and requests[0] <= now - 3600:
                requests.popleft()
            minute_requests = [stamp for stamp in requests if stamp > now - 60]
            if len(minute_requests) >= self.minute_limit:
                return max(1, int(60 - (minute_requests[0] - (now - 60))) + 1)
            if len(requests) >= self.hour_limit:
                return max(1, int(3600 - (requests[0] - (now - 3600))) + 1)
            requests.append(now)
            return None
