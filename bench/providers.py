"""HTTP-only adapters for benchmark providers; no vendor SDKs are used."""

import asyncio
import os
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx
from dotenv import load_dotenv


class ProviderError(RuntimeError):
    """An API response that could not produce a benchmark sample."""


class RateLimiter:
    """Evenly space requests using an injectable clock for deterministic tests."""

    def __init__(self, rpm: int, *, clock=time.monotonic, sleep=asyncio.sleep) -> None:
        self.interval = 60.0 / max(1, rpm)
        self.clock = clock
        self.sleep = sleep
        self.next_allowed = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self.clock()
            delay = max(0.0, self.next_allowed - now)
            if delay:
                await self.sleep(delay)
                now = self.clock()
            self.next_allowed = max(self.next_allowed, now) + self.interval


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After", "")
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - parsedate_to_datetime(response.headers["Date"])).total_seconds())
        except (KeyError, TypeError, ValueError):
            return min(30.0, 1.0 * (2**attempt))


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    rpm: int


class Provider:
    def __init__(self, config: ProviderConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.client = client
        self.limiter = RateLimiter(config.rpm)

    async def complete(self, system: str, user: str) -> str:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        try:
            for attempt in range(4):
                await self.limiter.wait()
                response = await client.post(self.url, headers=self.headers(), json=self.payload(system, user))
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 3:
                        await asyncio.sleep(_retry_after(response, attempt))
                        continue
                    raise ProviderError(f"{self.config.provider}: HTTP {response.status_code}")
                if not 200 <= response.status_code < 300:
                    raise ProviderError(f"{self.config.provider}: HTTP {response.status_code}")
                try:
                    return self.parse(response.json())
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProviderError(f"{self.config.provider}: invalid response") from exc
            raise ProviderError(f"{self.config.provider}: retries exhausted")
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.config.provider}: request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    @property
    def url(self) -> str:
        raise NotImplementedError

    def headers(self) -> dict[str, str]:
        raise NotImplementedError

    def payload(self, system: str, user: str) -> dict:
        raise NotImplementedError

    def parse(self, payload: dict) -> str:
        raise NotImplementedError


class GeminiProvider(Provider):
    @property
    def url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent"

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.config.api_key}

    def payload(self, system: str, user: str) -> dict:
        return {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": {"temperature": 0.8}}

    def parse(self, payload: dict) -> str:
        return "".join(part["text"] for part in payload["candidates"][0]["content"]["parts"] if "text" in part)


class GroqProvider(Provider):
    @property
    def url(self) -> str:
        return "https://api.groq.com/openai/v1/chat/completions"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    def payload(self, system: str, user: str) -> dict:
        return {"model": self.config.model, "temperature": 0.8, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}

    def parse(self, payload: dict) -> str:
        return payload["choices"][0]["message"]["content"]


def provider_for(name: str) -> Provider:
    load_dotenv()
    configs = {
        "gemini": (GeminiProvider, "GEMINI_MODEL", "GEMINI_API_KEY", "GEMINI_RPM", "8"),
        "groq_small": (GroqProvider, "GROQ_MODEL_SMALL", "GROQ_API_KEY", "GROQ_RPM", "15"),
        "groq_large": (GroqProvider, "GROQ_MODEL_LARGE", "GROQ_API_KEY", "GROQ_RPM", "15"),
    }
    if name not in configs:
        raise ValueError(f"unknown model alias: {name}")
    factory, model_var, key_var, rpm_var, default_rpm = configs[name]
    model, key = os.getenv(model_var), os.getenv(key_var)
    if not model or not key:
        raise ProviderError(f"{name}: missing required provider configuration")
    return factory(ProviderConfig(name, model, key, int(os.getenv(rpm_var, default_rpm))))


def model_id_for(name: str) -> str:
    """Resolve the configured model id without reading or exposing any API key."""
    load_dotenv()
    variables = {"gemini": "GEMINI_MODEL", "groq_small": "GROQ_MODEL_SMALL", "groq_large": "GROQ_MODEL_LARGE"}
    if name not in variables:
        raise ValueError(f"unknown model alias: {name}")
    model = os.getenv(variables[name])
    if not model:
        raise ProviderError(f"{name}: missing required provider configuration")
    return model
