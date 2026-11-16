# Changelog

All notable changes to VLMux will be documented here. The project follows semantic versioning.

## 0.2.0 - 2026-11-14

### Accessibility-tree refs (agent-desktop-style)

- Added Windows UI Automation accessibility snapshots with interactive elements tagged as
  `@<snapshot_id>:e<index>` refs (`pip install vlmux[uia]`), selected with
  `perception_mode = "ui_tree"`.
- Added the `click_ref` and `set_value_ref` VAP actions, resolved through a shared ref registry
  that re-walks the tree at action time. Elements that vanished fail with `stale_ref`; ambiguous
  matches fail with `ambiguous_target`; elements without headless patterns fail with
  `headless_not_supported`. Windows UIA invocation never moves the pointer or steals focus.
- Added one-shot agent-facing JSON envelope commands: `vlmux snapshot`, `vlmux click REF`,
  `vlmux set-value REF [--stdin]`. Snapshots persist under the user cache directory.
- Added MCP tools `desktop_snapshot`, `desktop_click`, `desktop_set_value` and ref-aware prompts;
  the model receives a compact ref listing instead of raw coordinates.
- Added `skills/vlmux-computer-use/SKILL.md` and `AGENTS.md` for agent-driven desktop use.
- Typed machine-readable error codes (`vlmux.exceptions.*.code`) on all errors; `ActionResult`
  now carries `error_code`.

### Reliability and safety

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
- HTTP API: fixed task execution being rejected by argument mismatch; added bearer-token auth
  (`VLMUX_API_TOKEN`/`--token`, mandatory for non-loopback binds), loopback `Host` enforcement,
  a 1 MiB request cap, bounded task store, and server-side error logging. See `docs/safety.md`.
- MCP: `computer.run_task` is wired to the runtime; invalid params return `-32602`, parse errors
  `-32700`; `computer.wait` is capped at 300000 ms; components are built lazily so
  `initialize`/`tools/list` work on headless machines.
- Policy engine: `open_app` and `browser_navigate` are classified `external_side_effect`;
  dangerous hotkey combos (`alt+f4`, `ctrl+w`, `win+r`, `cmd+q`, ...) are `destructive`; both
  classes require confirmation by default. Deny/confirm sets are copied defensively.
- Event bus isolates subscriber exceptions; trace/disk failures no longer abort task runs.
- Browser: back/forward navigate the correct history entry (`entryId`); browser observations
  report the real viewport instead of 1×1; CDP WebSocket is closed at the end of runs.
- Model adapters: envelope/transport parse failures now consume bounded repair attempts;
  truncated outputs fail fast with a clear `max_tokens` error; 3xx redirects and `InvalidURL`
  no longer crash or masquerade as connectivity failures; `Retry-After` is honored; retries
  include jitter; remote plain-HTTP endpoints are rejected unless loopback; custom providers
  cannot collide with built-in preset ids; offline localhost detection covers 127/8 and ::1.
- `CredentialStore.save_verified` no longer deletes a stored API key when re-verifying without
  one. Runtime treats unexpected executor/observer exceptions as failed steps; SoM rectangles,
  a11y windows, and HWND→int conversions no longer crash or corrupt bounds; POSIX executors map
  `cmd`/`meta`/`win` correctly to pynput's `cmd` key; macOS `open --args` forwards program
  arguments correctly; Windows window enumeration skips degenerate (minimized) windows.
- Benchmark: the final observation now reaches `SpecVerifier` so verifiers actually run; runner
  output no longer carries the internal observation blob; benchmark CLI builds model refs
  correctly, honors configured token prices, and isolates per-spec failures.
- SDK: `VLMux` accepts `confirmation_handler=`; `Computer.open_app` accepts arguments; ref
  convenience methods added.

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
