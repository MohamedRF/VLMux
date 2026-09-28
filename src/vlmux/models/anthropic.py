"""Native adapter for Anthropic-compatible Messages APIs."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from vlmux.core import AgentContext, ModelDecision, Observation, Task
from vlmux.exceptions import ActionValidationError, ModelConnectionError, ModelResponseError
from vlmux.models.base import AdapterConfig, ModelHealth, VisionSupport
from vlmux.models.helpers import build_vision_probe, model_ids, usage_integer
from vlmux.models.http import HTTPModelAdapter
from vlmux.models.parsing import normalize_action_coordinates, parse_model_action
from vlmux.models.prompt import build_anthropic_user_content, build_system_prompt


class AnthropicAdapter(HTTPModelAdapter):
    """Use the Anthropic Messages wire protocol for VLM decisions."""

    def __init__(self, config: AdapterConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config, client=client)

    async def decide(
        self,
        task: Task,
        observation: Observation,
        context: AgentContext,
    ) -> ModelDecision:
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": build_anthropic_user_content(task, observation, context),
            }
        ]
        started = perf_counter()
        last_error: ModelResponseError | None = None
        for attempt in range(self.config.repair_attempts + 1):
            payload = await self._post_messages(messages)
            raw_content, usage = self._extract_content(payload)
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
                input_tokens=usage_integer(usage, "input_tokens"),
                output_tokens=usage_integer(usage, "output_tokens"),
                metadata={"provider": self.config.provider},
            )
        raise last_error or ModelResponseError("model response validation failed")

    async def healthcheck(self) -> ModelHealth:
        try:
            response = await self._request("GET", "/v1/models")
            payload = response.json()
        except (ModelConnectionError, ValueError) as error:
            return ModelHealth(
                connected=False,
                provider=self.config.provider,
                model=self.config.model,
                detail=str(error),
            )
        available = model_ids(payload)
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
        """Verify base64 image blocks with a harmless random color image."""
        image_url, expected_color = build_vision_probe()
        encoded = image_url.split(",", 1)[1]
        try:
            response = await self._request(
                "POST",
                "/v1/messages",
                json={
                    "model": self.config.model,
                    "max_tokens": 32,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": encoded,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "Identify the dominant color in this image. Reply with "
                                        "only the lowercase English color name."
                                    ),
                                },
                            ],
                        }
                    ],
                },
            )
            payload = response.json()
            content, _ = self._extract_content(payload)
            if re.search(rf"\b{re.escape(expected_color)}\b", content.casefold()) is None:
                raise ModelResponseError("model did not correctly interpret the test image")
        except (ModelConnectionError, ModelResponseError, ValueError, IndexError) as error:
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

    async def _post_messages(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/v1/messages",
            json={
                "model": self.config.model,
                "max_tokens": 1024,
                "system": build_system_prompt(),
                "messages": messages,
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

    def _authorization_headers(self) -> dict[str, str]:
        if self.config.api_key is None:
            return {}
        return {"x-api-key": self.config.api_key.get_secret_value()}

    def _provider_headers(self) -> dict[str, str]:
        return {"anthropic-version": "2023-06-01"}

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ModelResponseError("model response omitted assistant content")
        text = "".join(
            block["text"]
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
        if not text:
            raise ModelResponseError("model assistant content was not text")
        usage = payload.get("usage", {})
        return text, usage if isinstance(usage, dict) else {}
