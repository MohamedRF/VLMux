# VLMux

**Give any vision-language model a computer.**

VLMux is a model-agnostic computer-use runtime under active development. It will connect
vision-language models to desktop and browser environments through a common perception and
action protocol.

```text
model → VLMux → browser / desktop
```

## Current status

- ✅ Repository foundation, typed core domain models, and VAP 1.0 action schemas
- ✅ Configuration precedence and foundational `version`, `doctor`, and `config` commands
- ✅ Screen capture, image resizing/encoding, coordinate mapping, and Windows desktop execution
- ✅ OpenAI-compatible, OpenRouter, and Ollama vision-model adapters
- ✅ Bounded runtime loop, policy checks, dry-run, events, and polished CLI
- 🚧 Set-of-Marks (next phase)
- 🗓 Browser mode, MCP, replay, and benchmarks

Windows desktop input is available through an isolated executor. MSS-based full-screen and monitor
capture are available where the operating system provides an interactive display. Active-window
capture is currently Windows-only.

## Quick start

VLMux requires Python 3.12 or newer.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"  # Windows
vlmux --help
vlmux version
vlmux doctor
vlmux config show
vlmux screenshot --output screenshot.png
vlmux models list
```

On macOS or Linux, activate the environment from `.venv/bin/activate` before installing.

## Configuration

Configuration precedence is CLI override, environment variable, TOML file, then default.
The default path is shown with `vlmux config path`.

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
confirm = ["sensitive", "destructive"]
deny = []
```

Supported environment variables are `VLMUX_MODEL`, `VLMUX_PROVIDER`, `VLMUX_API_KEY`,
`VLMUX_BASE_URL`, `VLMUX_MAX_STEPS`, and `VLMUX_OFFLINE`. Secret values are redacted from CLI
output.

## Models and runtime

Built-in providers are `ollama`, `openai-compatible`, `openai`, and `openrouter`.

```bash
# Local Ollama; no API key or network service outside localhost is required.
vlmux run --model ollama/qwen3-vl "Open Calculator and calculate 1729 multiplied by 47"

# Inspect one proposed action without moving the mouse or typing.
vlmux run --dry-run --model ollama/qwen3-vl "Open Calculator"

# OpenRouter model names can retain their provider/model path.
set VLMUX_API_KEY=...
vlmux run --model openrouter/google/gemini-model "Open Calculator"

vlmux models list
vlmux models test --model ollama/qwen3-vl
```

`--offline` rejects model URLs other than localhost. Model responses undergo JSON extraction,
Pydantic schema validation, coordinate normalization, coordinate bounds validation, and policy
evaluation before execution. Repair and network retries are bounded.

## Screen capture

```bash
# Capture the virtual desktop with configured resize limits.
vlmux screenshot --output desktop.png

# Capture physical monitor 1 as JPEG.
vlmux screenshot --monitor 1 --format jpeg --quality 85 --output monitor.jpg

# Windows: capture the foreground window.
vlmux screenshot --active-window --output active-window.png
```

The command refuses to overwrite an existing file unless `--force` is supplied. The standalone
screenshot and observe commands perform no network access. Runtime screenshots are sent only to
the explicitly configured model provider.

## Desktop executor

The Windows executor implements click, double-click, right-click, pointer movement, typing, key
presses, hotkeys, scrolling, dragging, and asynchronous wait actions. OS input is isolated behind
`ComputerExecutor`; tests use an injected backend and never move the CI machine's input devices.
Absolute coordinates support negative virtual-desktop positions used by left and upper monitors.
Shell-free application launching supports the initial calculator/text-editor workflow.

## Architecture

The core is provider-independent. Model adapters emit validated VAP actions; policies
approve those actions; platform executors will be solely responsible for OS interaction. See
[docs/architecture.md](docs/architecture.md), [docs/model-adapters.md](docs/model-adapters.md),
[docs/safety.md](docs/safety.md), and the exported schemas in [`schemas/`](schemas/).

## Safety and privacy

VLMux treats model output as untrusted input. Actions must pass schema, coordinate, and local
policy validation. Sensitive and destructive classes require confirmation by default. Screenshots
can contain sensitive information; choose local Ollama plus `--offline` when they must not leave
the machine.

## Development

```bash
ruff format --check .
ruff check .
mypy src
pytest
```

Contributions are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md) first.

Repository owner and maintainer: [MohamedRF](https://github.com/MohamedRF).

## License

MIT
