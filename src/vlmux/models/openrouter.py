"""OpenRouter specialization of the OpenAI-compatible adapter."""

from vlmux.models.openai_compatible import OpenAICompatibleAdapter


class OpenRouterAdapter(OpenAICompatibleAdapter):
    """Add OpenRouter attribution headers without duplicating transport logic."""

    def _provider_headers(self) -> dict[str, str]:
        return {
            "HTTP-Referer": "https://github.com/MohamedRF/VLMux",
            "X-Title": "VLMux",
        }
