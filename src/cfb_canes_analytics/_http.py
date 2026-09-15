"""Shared HTTP plumbing: request spacing, bounded exponential backoff, JSON GET.

Both exchanges throttle aggressively (Kalshi returns 429 within a few dozen naive
requests), so every call goes through a minimum inter-request interval and retries
with backoff on 429/5xx.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "cfb-canes-analytics (+https://github.com/DanielRegaladoUMiami/cfb-canes-analytics)"


class ApiError(RuntimeError):
    """Raised when an API returns an unrecoverable error."""


class RetryingClient:
    """Minimal rate-limit-aware JSON GET client over httpx."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 6,
        min_interval: float = 0.25,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last_request = 0.0
        self._client = client or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})

    def __enter__(self):  # noqa: ANN204 - returns Self
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _sleep_between_requests(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        params = {k: v for k, v in (params or {}).items() if v is not None}

        for attempt in range(self.max_retries):
            self._sleep_between_requests()
            response = self._client.get(url, params=params)
            self._last_request = time.monotonic()

            if response.status_code == 200:
                return response.json()

            if response.status_code in RETRY_STATUSES and attempt < self.max_retries - 1:
                delay = self.retry_delay(response, attempt)
                logger.warning(
                    "%s %s -> HTTP %s, retrying in %.1fs (attempt %d/%d)",
                    self.base_url,
                    path,
                    response.status_code,
                    delay,
                    attempt + 1,
                    self.max_retries,
                )
                time.sleep(delay)
                continue

            raise ApiError(
                f"GET {path} failed with HTTP {response.status_code}: {response.text[:300]}"
            )

        raise ApiError(f"GET {path} exhausted {self.max_retries} retries")

    @staticmethod
    def retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return min(2.0 * (2**attempt), 60.0)
