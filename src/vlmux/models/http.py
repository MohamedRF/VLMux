"""Shared, bounded HTTP transport for remote model adapters."""

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
            except httpx.RequestError as error:
                if attempt < self.config.request_retries:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise ModelConnectionError(
                    "unable to connect to the configured model provider"
                ) from error
            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < self.config.request_retries:
                await asyncio.sleep(0.25 * (2**attempt))
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
