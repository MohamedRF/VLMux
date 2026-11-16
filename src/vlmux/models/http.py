"""Shared, bounded HTTP transport for remote model adapters.

Note on proxy environment variables: httpx honors ``HTTP_PROXY``/``HTTPS_PROXY``
by default. That is convenient but means a hostile environment can route
credential-bearing model traffic through a proxy; clear those variables or set
``NO_PROXY=*`` if all model traffic must stay direct.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from vlmux.exceptions import ModelConnectionError
from vlmux.models.base import AdapterConfig, ModelAdapter


class HTTPModelAdapter(ModelAdapter):
    """Provide safe HTTP retries and lifecycle management to model adapters."""

    def __init__(self, config: AdapterConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.config.base_url.rstrip('/')}{path}"
        headers = dict(self._provider_headers())
        headers.update(self._authorization_headers())
        for attempt in range(self.config.request_retries + 1):
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)
            except (httpx.RequestError, httpx.InvalidURL) as error:
                if attempt < self.config.request_retries:
                    await asyncio.sleep(0.25 * (2**attempt) + (0.05 * attempt))
                    continue
                from urllib.parse import urlparse

                host = urlparse(self.config.base_url).hostname or "<invalid-url>"
                raise ModelConnectionError(
                    f"unable to connect to model provider at host {host}"
                ) from error
            if response.is_redirect:
                # Redirects are almost always endpoint misconfiguration; fail
                # closed instead of posting again or chasing an unknown target.
                raise ModelConnectionError(
                    f"model provider returned redirect HTTP {response.status_code}; "
                    "check the configured base_url"
                )
            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < self.config.request_retries:
                retry_after = response.headers.get("Retry-After", "").strip()
                try:
                    delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                except ValueError:
                    delay = 0.25 * (2**attempt)
                await asyncio.sleep(min(delay, 30.0))
                continue
            if response.is_error:
                raise ModelConnectionError(
                    f"model provider request failed with HTTP {response.status_code}"
                )
            return response
        raise ModelConnectionError("model provider request retries were exhausted")

    def _authorization_headers(self) -> dict[str, str]:
        if self.config.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"}

    def _provider_headers(self) -> dict[str, str]:
        return {}
