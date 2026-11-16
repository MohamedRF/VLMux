"""Generic adapter for OpenAI-compatible multimodal chat APIs."""

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
from vlmux.models.prompt import build_system_prompt, build_user_content


class OpenAICompatibleAdapter(HTTPModelAdapter):
    """Use an OpenAI-compatible chat-completions endpoint for VLM decisions."""

    def __init__(self, config: AdapterConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config, client=client)

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
            try:
                response = await self._post_chat(messages)
                raw_content, usage = self._extract_content(response)
                action = parse_model_action(raw_content)
                action = normalize_action_coordinates(action, observation.screen)
            except (ActionValidationError, ModelResponseError) as error:
                last_error = ModelResponseError(str(error))
                truncated = isinstance(error, ModelResponseError) and "truncat" in str(error)
                if truncated or attempt >= self.config.repair_attempts:
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
                input_tokens=usage_integer(usage, "prompt_tokens"),
                output_tokens=usage_integer(usage, "completion_tokens"),
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
        """Require the model to interpret a harmless random color image."""
        image_url, expected_color = build_vision_probe()
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

    async def _post_chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
        }
        if self.config.supports_json_mode:
            request["response_format"] = {"type": "json_object"}
        response = await self._request(
            "POST",
            "/chat/completions",
            json=request,
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise ModelResponseError("model provider returned non-JSON HTTP content") from error
        if not isinstance(payload, dict):
            raise ModelResponseError("model provider returned an invalid response envelope")
        return payload

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        try:
            choices = payload["choices"]
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ModelResponseError("model response omitted assistant content") from error
        if isinstance(finish_reason, str) and finish_reason == "length":
            raise ModelResponseError(
                "model output was truncated at max_tokens; request shorter output or raise the cap"
            )
        if not isinstance(content, str):
            raise ModelResponseError("model assistant content was not text")
        usage = payload.get("usage", {})
        return content, usage if isinstance(usage, dict) else {}
