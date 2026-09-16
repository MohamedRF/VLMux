# Model adapters

VLMux Phase 3 supports OpenAI-compatible multimodal chat APIs, OpenRouter, and Ollama. All three
implement the same `ModelAdapter` interface and return a provider-independent `ModelDecision`.

The generic adapter sends a provider-neutral system prompt, VAP JSON Schema, concise recent action
history, screenshot dimensions, and one base64 data URL. The model must return exactly one JSON
action. Responses pass through structured extraction, JSON parsing, Pydantic validation, image-to-
screen coordinate conversion, and runtime bounds/policy validation.

At most the configured number of repair attempts is made. Connection errors, rate limits, and
provider 5xx responses use bounded retries; computer actions are never retried by this layer.

Provider references:

```text
ollama/qwen3-vl
openrouter/google/gemini-model
openai/gpt-vision-model
```

For a custom endpoint, configure `provider = "openai-compatible"`, a model name, and an API base
URL ending at its OpenAI-compatible `/v1` root. `VLMUX_API_KEY` is sent only as a Bearer token to
that configured URL. It is never included in prompts, events, or CLI output.
