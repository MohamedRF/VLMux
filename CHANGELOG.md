# Changelog

All notable changes to VLMux will be documented here. The project follows semantic versioning.

## Unreleased

- Added native Anthropic Messages API support with image blocks, output repair, token usage, and
  image capability verification.
- Added Hugging Face, vLLM, and llama.cpp provider presets alongside the existing hosted and local
  OpenAI-compatible providers.
- Added protocol-selectable custom providers for OpenAI-compatible and Anthropic-compatible APIs.
- Added `--no-json-mode` for OpenAI-compatible models that do not implement `response_format`.
- Centralized provider HTTP retries, sanitized failures, authentication hooks, and client cleanup.
- Added data-driven presets for common OpenAI-compatible API providers and persisted custom
  provider definitions.
- Added `vlmux models add`, which performs a live image-input capability check before saving an API
  credential or custom provider.
- Added separate atomic `auth.json` credential storage with restrictive file permissions and
  runtime lookup of verified credentials.
- Changed `vlmux models test` to exercise real image input instead of connectivity alone.

## 0.1.0 - 2026-09-16

- Established the Python package, developer tooling, CI, and project documentation.
- Added strict VAP 1.0 action models and JSON Schema export.
- Added provider-independent task, observation, context, decision, action-result, and runtime-result
  models.
- Added centralized TOML/environment/CLI configuration loading.
- Added foundational `version`, `doctor`, and `config` commands.
- Added asynchronous MSS/Pillow screen capture with monitor and Windows active-window targeting,
  bounded resizing, PNG/JPEG encoding, and coordinate transforms.
- Added the `ComputerExecutor` abstraction, structured VAP dispatch, and a real Windows input
  backend for pointer, keyboard, scroll, drag, and wait actions.
- Added a safe `vlmux screenshot` command and Phase 2 capability checks to `vlmux doctor`.
- Added OpenAI-compatible, OpenRouter, and Ollama multimodal adapters with bounded retries and
  response repair, strict JSON/VAP validation, token usage capture, and a provider registry.
- Added the bounded runtime loop with observation, context, policy, confirmation, dry-run, timeout,
  failure handling, terminal actions, and lightweight events.
- Added `vlmux run`, `vlmux observe`, `vlmux models list`, and `vlmux models test`.
- Added shell-free Windows application launching for the first end-to-end desktop workflows.
