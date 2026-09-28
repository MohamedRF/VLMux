# Model adapters and providers

VLMux has data-driven presets for OpenAI, Anthropic, OpenRouter, Google Gemini, Hugging Face, Groq,
Together AI, Fireworks AI, DeepInfra, Mistral AI, xAI, Ollama, vLLM, and llama.cpp. Custom providers
use the same catalog and adapter registry. Every adapter returns a provider-independent
`ModelDecision`.

| Protocol adapter | Presets |
| --- | --- |
| OpenAI-compatible Chat Completions | OpenAI, OpenRouter, Gemini, Hugging Face, Groq, Together, Fireworks, DeepInfra, Mistral, xAI, Ollama, vLLM, llama.cpp, custom |
| Anthropic Messages | Anthropic, custom Anthropic-compatible gateways |

The presets describe transport compatibility, not a promise that every model exposed by a provider
is vision-capable. VLMux validates the exact selected model with a real image request.

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
gemini/gemini-model
my-custom-provider/vision-model
anthropic/claude-vision-model
huggingface/vendor/vision-model
vllm/served-model-name
llamacpp/served-model-name
```

## Connecting a model

Use `vlmux models add --provider PROVIDER --model MODEL`. For a custom provider, also supply a
unique provider ID and its OpenAI-compatible base URL:

```text
vlmux models add --provider my-vlm --name "My VLM" \
  --base-url https://models.example/v1 --model vision-model
```

For an Anthropic-compatible gateway, select its native protocol and provide the API root (VLMux
appends `/v1/messages`):

```text
vlmux models add --provider claude-gateway --protocol anthropic \
  --base-url https://models.example --model vision-model
```

For an OpenAI-compatible server or model that rejects `response_format`, add it with
`--no-json-mode`. VLMux still requires strict JSON through its prompt and validates the response
before any action reaches the executor.

Before anything is saved, VLMux sends a harmless, randomly selected solid-color PNG data URL to the
selected model through `/chat/completions`. The model must correctly identify the color, proving
that the configured credential, endpoint, and model can interpret the image representation used by
the runtime. Authentication failures, text-only models, incorrect visual answers, incompatible
endpoints, empty responses, and network failures all prevent the save. Provider response bodies
are not exposed in the error.

Credentials are stored in the user configuration directory's `auth.json`; custom definitions are
stored in `providers.json`. The credential file is separate from ordinary settings and is written
atomically with mode `0600` where supported. `VLMUX_API_KEY` takes precedence over saved
credentials. API keys are never included in prompts, events, normal configuration output, or model
verification output.

Custom OpenAI-compatible endpoints use Bearer-token authentication. Custom Anthropic-compatible
endpoints use `x-api-key` and the versioned Messages API headers. Arbitrary authentication schemes,
custom request templates, cloud-provider signing (such as AWS SigV4), and provider-native computer-
use action formats are not yet supported.
