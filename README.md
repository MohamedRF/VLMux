# VLMux

**Give any vision-language model a computer.**

[![CI](https://github.com/MohamedRF/VLMux/actions/workflows/ci.yml/badge.svg)](https://github.com/MohamedRF/VLMux/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

VLMux is a model-agnostic computer-use runtime. It connects vision-language models (VLMs)
to desktop and browser environments through a single, typed perception-and-action protocol:

```text
model → VLMux → browser / desktop
```

The model proposes actions; VLMux validates them against the VAP protocol, evaluates local
policy, and only then executes them on the machine. No model ever gets raw, unchecked access
to the OS.

## Features

- **Provider-agnostic model adapters** — OpenAI-compatible and native Anthropic protocols, with
  presets for OpenAI, Anthropic, OpenRouter, Google Gemini, Hugging Face, Groq, Together AI,
  Fireworks AI, DeepInfra, Mistral AI, xAI, Ollama, vLLM and llama.cpp. Custom endpoints and
  custom protocols are supported.
- **Typed action protocol (VAP 1.0)** — every model response is JSON-extracted, Pydantic-validated,
  coordinate-normalized and bounds-checked before it reaches an executor.
- **Desktop executors for Windows, macOS and Linux** — click, double-click, right-click, move,
  type, keys, hotkeys, scroll, drag and wait. Absolute coordinates handle negative
  virtual-desktop positions used by left/upper monitors.
- **Multiple perception modes** — raw screenshots, Set-of-Marks (`set_of_marks`, `hybrid`),
  OCR (`ocr`), accessibility tree (`a11y`), and a stable element-ref mode (`ui_tree`, Windows UIA).
- **Browser mode over CDP** — navigate, go back/forward, reload, and semantic DOM clicks that
  prefer elements over pixel coordinates.
- **Agent-facing interfaces** — MCP server (`vlmux mcp` / `vlmux-mcp`), local REST API
  (`vlmux serve`), Python SDK (`VLMux`, `Computer`), and JSON-envelope CLI commands
  (`vlmux snapshot`, `vlmux click @ref`, `vlmux set-value @ref`).
- **Bounded runtime loop** — step/time/failure budgets, policy evaluation with
  confirmation-required action classes, dry-run mode, and repair/network retries.
- **Safety by default** — schema + coordinate + policy validation on every action;
  `--offline` restricts model URLs to localhost; secrets are redacted from CLI output and stored
  with user-only permissions.
- **Replay and benchmarks** — opt-in run recording (`vlmux replay`) and TOML-defined benchmarks
  with verifiers (`vlmux benchmark`).

## Requirements

- Python **3.12** or newer
- An interactive display for desktop control (mss-based capture)
- A Chrome/Chromium instance with CDP exposed for browser mode
- An image-capable model endpoint (local or hosted)

## Installation

```bash
git clone https://github.com/MohamedRF/VLMux.git
cd VLMux
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Optional extras:

| Extra     | Purpose                                        |
| --------- | ---------------------------------------------- |
| `uia`     | Windows accessibility-tree snapshots (`ui_tree`) — `pip install vlmux[uia]` |
| `ocr`     | OCR perception mode                            |
| `browser` | CDP browser mode                               |

## Quick start

```bash
vlmux --help
vlmux version
vlmux doctor                 # environment and configuration self-check
vlmux models list
vlmux screenshot --output screenshot.png
```

Connect a model — the API key is prompted for without echoing it, and VLMux sends a small
image request to verify the model actually answers about images before saving anything:

```bash
vlmux models add --provider openrouter --model google/gemini-2.5-pro
```

Run a task (a local model needs no network access beyond localhost):

```bash
vlmux run --model ollama/qwen3-vl "Open Calculator and calculate 1729 multiplied by 47"
```

Inspect one proposed action without moving the mouse or typing:

```bash
vlmux run --dry-run --model ollama/qwen3-vl "Open Calculator"
```

## Documentation

- [Architecture](docs/architecture.md) — runtime loop, components and data flow
- [Safety model](docs/safety.md) — validation, policy classes and threat model
- [Protocol (VAP)](docs/protocol.md) — action schema and `schemas/`
- [Model adapters](docs/model-adapters.md) — provider presets and custom endpoints
- [Accessibility refs](docs/a11y-refs.md) — `ui_tree` snapshots and `click_ref` workflows
- [MCP server](docs/mcp.md) — tools exposed to MCP clients
- [Benchmarks](docs/benchmarks.md) — defining and running benchmark suites
- [CHANGELOG](CHANGELOG.md) — notable changes

## Configuration

Precedence: CLI flag → environment variable → TOML file → built-in default.
Show the active file with `vlmux config path`.

```toml
[model]
provider = "ollama"
name = "qwen3-vl"
base_url = "http://localhost:11434/v1"

[runtime]
max_steps = 50
max_runtime_seconds = 300
max_failures = 3
model_repair_attempts = 1
model_request_retries = 2
model_timeout_seconds = 60

[perception.screenshot]
max_width = 1440
max_height = 1440
format = "png"
quality = 85

[policy]
confirm = ["sensitive", "external_side_effect", "destructive"]
deny = []
```

Environment variables: `VLMUX_MODEL`, `VLMUX_PROVIDER`, `VLMUX_API_KEY`, `VLMUX_BASE_URL`,
`VLMUX_MAX_STEPS`, `VLMUX_OFFLINE`. Secrets are redacted from CLI output.

Saved credentials live in `auth.json` beside the platform-specific configuration file — never in
`config.toml` — and custom provider definitions in `providers.json`. Both are created with
user-only permissions where the OS supports them. `VLMUX_API_KEY` overrides a saved credential.
Treat `auth.json` as a secret; never commit or share it.

## Perception modes

```toml
[runtime]
perception_mode = "raw"  # raw | set_of_marks | hybrid | ocr | a11y | ui_tree
```

- `set_of_marks` draws numbered red badges over detected UI elements; the model may then answer
  `{"type": "click_mark", "mark": 3}` and the runtime resolves it to coordinates.
- `hybrid` adds OCR text alongside marks.
- `ui_tree` (Windows, requires `vlmux[uia]`) tags every interactive accessibility element with a
  stable ref such as `@s1a2b3:e8`. Ref actions invoke the UIA element directly — the pointer does
  not move and focus is not taken — and fail closed with `stale_ref` when the UI changed instead
  of clicking the wrong thing:

  ```json
  {"type": "click_ref", "ref": "@s1a2b3:e8"}
  {"type": "set_value_ref", "ref": "@s1a2b3:e3", "value": "Ada"}
  ```

  See [docs/a11y-refs.md](docs/a11y-refs.md) for the one-shot `vlmux snapshot` / `vlmux click` /
  `vlmux set-value` commands and the MCP `desktop_snapshot`, `desktop_click`, `desktop_set_value`
  tools.

## Browser mode

```toml
[runtime]
browser_cdp_url = "ws://127.0.0.1:9222/devtools/page/1"
```

Start Chrome with `--remote-debugging-port=9222`, then run tasks. `browser_navigate`,
`browser_back`, `browser_forward` and `browser_reload` route to CDP; semantic element clicks
prefer the DOM over pixel coordinates.

## MCP, REST API and Python SDK

```bash
vlmux mcp      # MCP server over stdio (also: vlmux-mcp)
vlmux serve    # REST API on http://127.0.0.1:8765
```

```python
from vlmux import VLMux, Computer

agent = VLMux(model="ollama/qwen3-vl")
result = await agent.run("Open calculator and calculate 42 * 88")

computer = Computer()
await computer.click(100, 200)
```

## Replay and benchmarks

```toml
[runtime]
record_runs = true
runs_dir = "runs"
```

```bash
vlmux replay RUN_ID
vlmux benchmark benchmarks --model ollama/qwen3-vl --model openrouter/google/gemini-2.5-pro
```

## Architecture and safety

The core is provider-independent: model adapters emit validated VAP actions, the policy engine
gates them, and platform executors perform them. VLMux treats model output as untrusted input —
every action must pass schema, coordinate and local-policy validation. Sensitive,
external-side-effect (launching applications, browser navigation) and destructive action classes
require confirmation by default. Screenshots can contain sensitive information; choose local
Ollama with `--offline` when they must not leave the machine.

Tests never move the CI machine's input devices: OS input is isolated behind `ComputerExecutor`
with an injected backend.

## Development

```bash
ruff format --check .
ruff check .
mypy src            # or: mypy --platform linux src, to match CI on Linux
pytest
```

Contributions are welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md)
first. Generated schemas must be refreshed with `python scripts/export_schemas.py` after protocol
changes.

Maintainer: [MohamedRF](https://github.com/MohamedRF).

## License

[MIT](LICENSE)
