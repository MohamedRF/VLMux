"""Generic adapter for OpenAI-compatible multimodal chat APIs."""

from __future__ import annotations

import asyncio
import base64
import re
import secrets
from io import BytesIO
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image

from vlmux.core import AgentContext, ModelDecision, Observation, Task
from vlmux.exceptions import ActionValidationError, ModelConnectionError, ModelResponseError
from vlmux.models.base import AdapterConfig, ModelAdapter, ModelHealth, VisionSupport
from vlmux.models.parsing import normalize_action_coordinates, parse_model_action
from vlmux.models.prompt import build_system_prompt, build_user_content


class OpenAICompatibleAdapter(ModelAdapter):
    """Use an OpenAI-compatible chat-completions endpoint for VLM decisions."""

    def __init__(self, config: AdapterConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

    async def decide(
        self,
        task: Task,
        observation: Observation,
        context: AgentContext,
    ) -> ModelDecision:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt()},
            {
                "role": "user",
                "content": build_user_content(task, observation, context),
            },
        ]
        started = perf_counter()
        last_error: ModelResponseError | None = None
        for attempt in range(self.config.repair_attempts + 1):
            response = await self._post_chat(messages)
            raw_content, usage = self._extract_content(response)
            try:
                action = parse_model_action(raw_content)
                action = normalize_action_coordinates(action, observation.screen)
            except (ActionValidationError, ModelResponseError) as error:
                last_error = ModelResponseError(str(error))
                if attempt >= self.config.repair_attempts:
                    break
                messages.extend(
                    [
                        {"role": "assistant", "content": raw_content},
                        {
                            "role": "user",
                            "content": (
                                "Your response was invalid. Return exactly one JSON object that "
                                "matches the VAP schema. Do not include markdown or explanation."
                            ),
                        },
                    ]
                )
                continue
            action = action.model_copy(
                update={
                    "id": action.id or f"action_{uuid4().hex}",
                    "source_model": action.source_model or self.config.model,
                }
            )
            return ModelDecision(
                action=action,
                latency_ms=(perf_counter() - started) * 1000,
                input_tokens=_usage_integer(usage, "prompt_tokens"),
                output_tokens=_usage_integer(usage, "completion_tokens"),
                metadata={"provider": self.config.provider},
            )
        raise last_error or ModelResponseError("model response validation failed")

    async def healthcheck(self) -> ModelHealth:
        try:
            response = await self._request("GET", "/models")
            payload = response.json()
        except (ModelConnectionError, ValueError) as error:
            return ModelHealth(
                connected=False,
                provider=self.config.provider,
                model=self.config.model,
                detail=str(error),
            )
        available = _model_ids(payload)
        detail = "provider connected"
        if available and self.config.model not in available:
            detail = "provider connected; configured model was not listed"
        return ModelHealth(
            connected=True,
            provider=self.config.provider,
            model=self.config.model,
            detail=detail,
            metadata={"available_models": len(available)},
        )

    async def check_image_input(self) -> VisionSupport:
        """Require the model to interpret a harmless random color image."""
        image_url, expected_color = _build_vision_probe()
        try:
            response = await self._request(
                "POST",
                "/chat/completions",
                json={
                    "model": self.config.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "This is an image-input capability check. "
                                        "Identify the dominant color in the attached image. "
                                        "Reply with only the lowercase English color name."
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                },
                            ],
                        }
                    ],
                    "temperature": 0,
                },
            )
            payload = response.json()
            content, _ = self._extract_content(payload)
            if not content.strip():
                raise ModelResponseError("model returned empty assistant content")
            if re.search(rf"\b{re.escape(expected_color)}\b", content.casefold()) is None:
                raise ModelResponseError("model did not correctly interpret the test image")
        except (ModelConnectionError, ModelResponseError, ValueError) as error:
            return VisionSupport(
                accepted=False,
                provider=self.config.provider,
                model=self.config.model,
                detail=f"image input was rejected or not usable: {error}",
            )
        return VisionSupport(
            accepted=True,
            provider=self.config.provider,
            model=self.config.model,
            detail="model correctly interpreted image input",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post_chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/chat/completions",
            json={
                "model": self.config.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise ModelResponseError("model provider returned non-JSON HTTP content") from error
        if not isinstance(payload, dict):
            raise ModelResponseError("model provider returned an invalid response envelope")
        return payload

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.config.base_url.rstrip('/')}{path}"
        headers = dict(self._provider_headers())
        if self.config.api_key is not None:
            headers["Authorization"] = f"Bearer {self.config.api_key.get_secret_value()}"
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

    def _provider_headers(self) -> dict[str, str]:
        return {}

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        try:
            choices = payload["choices"]
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelResponseError("model response omitted assistant content") from error
        if not isinstance(content, str):
            raise ModelResponseError("model assistant content was not text")
        usage = payload.get("usage", {})
        return content, usage if isinstance(usage, dict) else {}


def _build_vision_probe() -> tuple[str, str]:
    """Return an unpredictable, easy-to-recognize image challenge."""
    colors = {
        "red": (255, 0, 0),
        "green": (0, 160, 0),
        "blue": (0, 80, 255),
        "yellow": (255, 220, 0),
        "purple": (145, 40, 180),
        "orange": (255, 125, 0),
    }
    name = secrets.choice(tuple(colors))
    image = Image.new("RGB", (64, 64), colors[name])
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    payload = base64.b64encode(encoded.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}", name


def _usage_integer(usage: dict[str, Any], key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) and value >= 0 else None


def _model_ids(payload: object) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return set()
    return {
        item["id"]
        for item in payload["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
