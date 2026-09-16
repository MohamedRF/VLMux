"""Ollama adapter using its OpenAI-compatible local endpoint."""

from vlmux.models.openai_compatible import OpenAICompatibleAdapter


class OllamaAdapter(OpenAICompatibleAdapter):
    """Local Ollama VLM adapter with shared request and validation behavior."""
