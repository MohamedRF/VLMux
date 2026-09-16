# VLMux — Universal Computer-Use Runtime for Vision-Language Models

You are the principal engineer responsible for designing and implementing **VLMux**, an open-source, model-agnostic computer-use runtime.

## 1. Project Vision

Build:

> **VLMux — Give any vision-language model a computer.**

VLMux should provide a universal runtime that allows vision-language models, multimodal LLMs, agent harnesses, local models, and API-hosted models to observe and interact with a computer through a common interface.

The core idea is:

```text
Vision Model
      ↓
Model Adapter
      ↓
VLMux Observation
      ↓
Model Reasoning
      ↓
Universal Action Protocol
      ↓
Safety / Policy Engine
      ↓
Action Executor
      ↓
Computer
      ↓
New Observation
      ↓
Repeat
```

VLMux must NOT be tied to one model vendor.

The long-term goal is to support:

* OpenAI
* Anthropic
* Gemini
* OpenRouter
* Ollama
* vLLM
* llama.cpp
* Hugging Face-hosted models
* OpenAI-compatible APIs
* Custom HTTP VLM endpoints
* Native computer-use models
* Function/tool-calling VLMs
* Vision models that only return text/JSON

And expose the runtime through:

* CLI
* Python SDK
* TypeScript SDK
* MCP server
* REST API
* WebSocket event stream
* future agent-harness adapters

The system should eventually work on:

* Windows
* macOS
* Linux
* Browsers through Chrome DevTools Protocol

However, prioritize a clean architecture over implementing every platform immediately.

---

# 2. Core Design Philosophy

VLMux is infrastructure, not another chatbot or another monolithic autonomous agent.

Its responsibility is:

```text
MODEL
  ↓
UNDERSTAND SCREEN
  ↓
PROPOSE ACTION
  ↓
NORMALIZE ACTION
  ↓
VALIDATE ACTION
  ↓
EXECUTE ACTION
  ↓
OBSERVE RESULT
```

The model should be replaceable without changing the rest of the runtime.

Likewise, the desktop/browser executor should be replaceable without changing the model integration.

All major components must therefore communicate through explicit interfaces.

Avoid tightly coupled code.

---

# 3. Repository Architecture

Create a clean monorepo structure similar to:

```text
vlmux/
│
├── apps/
│   ├── cli/
│   └── server/
│
├── packages/
│   ├── core/
│   ├── protocol/
│   ├── runtime/
│   ├── models/
│   ├── perception/
│   ├── executors/
│   ├── browser/
│   ├── policy/
│   ├── memory/
│   ├── mcp/
│   ├── sdk-python/
│   └── sdk-typescript/
│
├── examples/
│   ├── openai/
│   ├── openrouter/
│   ├── ollama/
│   ├── custom-model/
│   └── mcp/
│
├── benchmarks/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docs/
│   ├── architecture.md
│   ├── protocol.md
│   ├── model-adapters.md
│   ├── safety.md
│   ├── mcp.md
│   └── contributing.md
│
├── scripts/
│
├── .github/
│   └── workflows/
│
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── CHANGELOG.md
```

You may improve this structure if there is a technically superior organization.

Before changing it significantly, document the reason.

---

# 4. Recommended Technology

Use **Python 3.12+** for the main runtime.

Use strong typing everywhere.

Recommended libraries may include:

```text
Python
├── pydantic
├── typer
├── httpx
├── asyncio
├── pillow
├── mss
├── platformdirs
├── rich
├── tenacity
└── pytest
```

For browser automation prefer:

```text
Chrome DevTools Protocol
```

or a thin abstraction around it.

Do NOT make Playwright the architectural foundation.

It may be supported as an executor later, but VLMux should expose its own browser abstraction.

For desktop actions, design an executor interface first.

Platform-specific backends can use suitable native or third-party libraries.

Do not scatter operating-system-specific checks throughout the application.

Use:

```text
DesktopExecutor
    ├── WindowsExecutor
    ├── MacOSExecutor
    └── LinuxExecutor
```

---

# 5. Universal Action Protocol

Create a central protocol representing all actions.

Call this:

# VAP — VLMux Action Protocol

Every model adapter must eventually produce VAP actions.

Example:

```json
{
  "version": "1.0",
  "type": "click",
  "target": {
    "x": 840,
    "y": 512
  },
  "confidence": 0.92
}
```

Support initial actions:

```text
click
double_click
right_click

move_cursor

type
paste

key
hotkey

scroll

drag

wait

screenshot

open_app

focus_window

close_window

browser_navigate

browser_back

browser_forward

browser_reload

finish

fail
```

Represent these as typed models.

Prefer discriminated unions.

Example conceptual implementation:

```python
Action =
    ClickAction |
    TypeAction |
    ScrollAction |
    HotkeyAction |
    WaitAction |
    FinishAction
```

Actions must be serializable to JSON.

Each action should support:

```text
version
type
timestamp
source_model
confidence
metadata
```

when appropriate.

Do not force unnecessary fields on every action.

---

# 6. Observation Protocol

Create a standardized observation object.

Example:

```json
{
  "id": "obs_123",
  "timestamp": "...",
  "screen": {
    "width": 1920,
    "height": 1080,
    "image": "..."
  },
  "cursor": {
    "x": 600,
    "y": 400
  },
  "active_window": {
    "title": "Visual Studio Code",
    "application": "Code"
  }
}
```

Later it must support:

```text
screenshot
OCR
accessibility tree
DOM
browser metadata
cursor position
active application
window list
clipboard metadata
Set-of-Marks annotations
```

The observation system must support multiple perception modes.

---

# 7. Perception Modes

Design these modes now, even if only some are implemented initially.

## RAW

Model receives:

```text
screenshot only
```

## OCR

Model receives:

```text
screenshot
+
recognized text
+
text coordinates
```

## A11Y

Model receives:

```text
screenshot
+
accessibility tree
```

## DOM

For browsers:

```text
screenshot
+
DOM
+
interactive element metadata
```

## SET-OF-MARKS

Detect relevant interactive elements.

Overlay numbered labels:

```text
[1]
[2]
[3]
```

The model can return:

```json
{
  "type": "click_mark",
  "mark": 3
}
```

The runtime resolves the mark to coordinates.

## HYBRID

Combine the available perception sources intelligently.

Design the abstraction such that future perception providers can be added through plugins.

---

# 8. Model Adapter Architecture

Create:

```python
class ModelAdapter(ABC):
    async def decide(
        self, task: Task, observation: Observation, context: AgentContext
    ) -> ModelDecision: ...
```

Support three primary adapter strategies.

## Mode A — Native Computer Use

For models that already return native computer actions.

Adapter converts:

```text
provider action
        ↓
VAP action
```

## Mode B — Tool Calling

The model receives tools such as:

```text
computer.click
computer.type
computer.scroll
computer.hotkey
```

Provider-specific calls are normalized into VAP.

## Mode C — Structured Text

For ordinary VLMs.

Prompt the model to return strict JSON:

```json
{
  "action": "click",
  "x": 500,
  "y": 300
}
```

Parse and validate the result.

If JSON parsing fails:

```text
attempt controlled repair
```

Never execute malformed model output.

---

# 9. Initial Model Providers

Implement adapters incrementally.

Start with:

```text
OpenAI-compatible
OpenRouter
Ollama
Custom HTTP endpoint
```

The OpenAI-compatible provider is especially important because many services expose the same API convention.

Then structure placeholders for:

```text
OpenAI native
Anthropic
Gemini
vLLM
llama.cpp
```

Do not duplicate code unnecessarily.

Example:

```text
OpenAICompatibleAdapter
          ↑
     OpenRouterAdapter
```

when appropriate.

---

# 10. Runtime Loop

Implement the fundamental agent loop.

Conceptually:

```python
while True:
    observation = await observer.capture()

    decision = await model.decide(task, observation, context)

    action = protocol.normalize(decision)

    policy_result = policy.validate(action)

    if policy_result.requires_confirmation:
        ...

    if not policy_result.allowed:
        ...

    result = await executor.execute(action)

    memory.record(observation, decision, action, result)

    if action.type in ("finish", "fail"):
        break
```

The loop needs limits.

Support:

```text
max_steps
max_runtime
max_failures
max_retries
```

Never allow accidental infinite loops.

---

# 11. Agent Context

The model should receive concise context describing previous actions.

Example:

```text
Task:
Open calculator and calculate 24 × 73.

Previous steps:

1. Screenshot captured.
2. Clicked Calculator icon.
3. Calculator opened.
4. Clicked 2.
5. Clicked 4.

Current screenshot:
<image>
```

Do not blindly feed every previous screenshot into the context.

Implement context management.

Possible strategy:

```text
latest observation
+
recent actions
+
task
+
important state
+
optional compressed history
```

---

# 12. Safety / Policy Engine

Safety is a first-class architectural requirement.

Create:

```text
PolicyEngine
```

that runs before actions execute.

Actions may be classified:

```text
SAFE

SENSITIVE

DESTRUCTIVE

EXTERNAL_SIDE_EFFECT
```

Examples.

SAFE:

```text
scroll
move cursor
open app
read page
```

SENSITIVE:

```text
paste clipboard
read private information
```

EXTERNAL_SIDE_EFFECT:

```text
send message
submit form
make purchase
publish post
```

DESTRUCTIVE:

```text
delete file
terminate process
remove repository
format disk
```

The policy layer should be configurable.

Support:

```yaml
policy:
  confirm:
    - external_side_effect
    - destructive

  deny:
    - format_disk
```

Never rely solely on the model to determine whether an action is safe.

---

# 13. Dry-Run Mode

Implement:

```bash
vlmux run --dry-run "task"
```

In dry-run mode:

```text
observe
reason
generate actions
validate actions
```

but:

```text
DO NOT execute actions.
```

Display proposed actions.

This is important for debugging and safety.

---

# 14. CLI

Create an excellent developer CLI.

Command:

```bash
vlmux
```

Use Typer and Rich or equivalent.

Initial commands:

```bash
vlmux run

vlmux models

vlmux models list
vlmux models add
vlmux models test

vlmux config

vlmux doctor

vlmux screenshot

vlmux observe

vlmux serve

vlmux mcp

vlmux replay

vlmux benchmark

vlmux version
```

Example:

```bash
vlmux run \
  --model ollama/qwen3-vl \
  "Open calculator and calculate 725 * 31"
```

Another:

```bash
vlmux run \
  --model openrouter/google/gemini-model \
  --max-steps 30 \
  "Open Chrome and visit GitHub"
```

Support environment variables.

Example:

```text
VLMUX_MODEL
VLMUX_PROVIDER
VLMUX_API_KEY
VLMUX_BASE_URL
VLMUX_MAX_STEPS
```

Never write API keys into logs.

---

# 15. Configuration

Create configuration under a platform-appropriate directory.

Support:

```yaml
model:
  provider: ollama
  name: qwen3-vl

runtime:
  max_steps: 50

perception:
  mode: hybrid

policy:
  confirmation: true
```

Provide:

```bash
vlmux config show
```

and:

```bash
vlmux config path
```

Environment variables should override file configuration.

CLI parameters should override environment variables.

Use precedence:

```text
CLI
>
environment
>
configuration file
>
defaults
```

---

# 16. Model Registry

Implement an internal model registry.

Example:

```python
registry.register(provider="ollama", adapter=OllamaAdapter)
```

Adding a provider should NOT require modifying the core runtime.

Eventually support plugin discovery.

Possible concept:

```text
vlmux-provider-ollama
vlmux-provider-gemini
vlmux-provider-anthropic
```

Do not prematurely split packages, but architect for this future.

---

# 17. Executor Architecture

Define:

```python
class ComputerExecutor(ABC):
    async def click(...)
    async def type(...)
    async def scroll(...)
    async def hotkey(...)
    async def drag(...)
```

Do not allow provider code to call OS libraries directly.

Provider:

```text
model → action
```

Executor:

```text
action → operating system
```

These layers must remain completely separate.

---

# 18. Browser Executor

Create a dedicated browser control layer.

Prefer the following action hierarchy:

```text
DOM action
      ↓ if unavailable

Accessibility action
      ↓ if unavailable

Pixel coordinate action
```

This provides fallback behavior.

Browser capabilities should eventually include:

```text
navigate
click element
type into element
scroll
inspect DOM
retrieve page text
retrieve interactive elements
screenshots
tabs
cookies/session metadata where permitted
```

Do not make browser mode dependent upon coordinates when semantic control is possible.

---

# 19. Coordinate System

Define the coordinate system carefully.

All raw coordinate actions should use either:

```text
absolute screen pixels
```

or a canonical normalized system such as:

```text
0–1000
```

If normalized coordinates are supported, conversion must happen in one well-tested location.

Models may emit coordinates in various conventions.

Adapters must normalize them.

Examples:

```text
1920 x 1080 screenshot

model:
x = 500 / 1000

runtime:
x = 960 px
```

Support high-DPI screens correctly.

---

# 20. Screen Capture

Create:

```text
ScreenCaptureProvider
```

Capabilities:

```text
capture full screen
capture monitor
capture active window
resize screenshot
compress screenshot
encode image
```

Do not unnecessarily send 4K images to models.

Implement configurable resolution.

Example:

```yaml
perception:
  screenshot:
    max_width: 1440
    format: jpeg
    quality: 85
```

Coordinate transformations must remain correct after resizing.

---

# 21. Action Results

Every executed action should return a result.

Example:

```json
{
  "success": true,
  "duration_ms": 72,
  "error": null
}
```

Model context should know whether the previous action succeeded.

Never silently swallow executor errors.

---

# 22. Event System

Design an event bus.

Potential events:

```text
task.started

observation.created

model.requested

model.responded

action.proposed

action.approved

action.rejected

action.executed

action.failed

step.completed

task.completed

task.failed
```

Users should later be able to subscribe through:

```text
Python callbacks
WebSocket
logs
UI
```

---

# 23. Logging

Use structured logs.

Support:

```bash
vlmux run --verbose
```

and:

```bash
vlmux run --debug
```

Never log:

```text
API keys
authorization headers
passwords
raw secrets
```

Create action trace IDs.

Example:

```text
task_id
step_id
observation_id
action_id
```

---

# 24. Replay System

Store optional task traces.

Example:

```text
runs/
  2026-09-16-calculator/
      task.json
      events.jsonl
      screenshots/
          001.jpg
          002.jpg
```

Then:

```bash
vlmux replay RUN_ID
```

Replay should help developers debug agent behavior.

Be conscious that screenshots can contain sensitive information.

Trace storage must therefore be opt-in or clearly configurable.

---

# 25. Benchmark Framework

Create an extensible benchmark format.

Example:

```yaml
name: calculator_multiplication

task:
  Open Calculator and calculate 1729 multiplied by 47.

success:
  type: screen_contains
  value: "81263"

max_steps: 20
```

Eventually allow:

```bash
vlmux benchmark run benchmarks/basic
```

Report:

```text
model
task
success
steps
tokens
latency
cost
```

This could become a major part of VLMux.

The project should ultimately allow developers to compare computer-use capability across different VLMs.

---

# 26. Cost Tracking

Design model responses so token usage and cost can be recorded where providers expose it.

Example:

```text
input_tokens
output_tokens
images
latency
estimated_cost
```

Future command:

```bash
vlmux benchmark --models \
  openai/... \
  openrouter/... \
  ollama/...
```

could compare:

```text
success rate
average steps
average latency
average cost
```

Local models should show cost as:

```text
local
```

rather than fake monetary estimates.

---

# 27. MCP Server

Implement an MCP server exposing computer capabilities.

Initial tools:

```text
computer.observe

computer.screenshot

computer.click

computer.double_click

computer.type

computer.hotkey

computer.scroll

computer.drag

computer.wait

computer.windows

computer.open_app
```

Also expose a higher-level tool:

```text
computer.run_task
```

Example:

```json
{
  "task": "Open Chrome and search for VLMux"
}
```

The MCP implementation must use the same core runtime.

Do NOT implement separate duplicate computer-control logic for MCP.

---

# 28. REST API

Eventually provide:

```text
POST /v1/tasks

GET /v1/tasks/:id

POST /v1/actions

GET /v1/observe

GET /health
```

A task request could look like:

```json
{
  "task": "Open VS Code",
  "model": "ollama/qwen3-vl",
  "max_steps": 20
}
```

Use the same runtime underneath.

No duplicated agent loop.

---

# 29. Python SDK

Desired API:

```python
from vlmux import VLMux

agent = VLMux(model="ollama/qwen3-vl")

result = await agent.run("Open calculator and calculate 42 * 88")

print(result)
```

Also allow low-level control:

```python
from vlmux import Computer

computer = Computer()

await computer.click(100, 200)
await computer.type("Hello")
```

---

# 30. TypeScript SDK

Desired future API:

```typescript
import { VLMux } from "@vlmux/sdk";

const agent = new VLMux({
  model: "openrouter/model-name"
});

await agent.run(
  "Open Chrome and navigate to GitHub"
);
```

Do not build TypeScript SDK before the protocol stabilizes.

Prepare protocol JSON schemas first.

---

# 31. Prompt Template

Create the system prompt used for generic VLM adapters.

It should tell the model:

```text
You are controlling a computer.

You will receive:

1. A task.
2. A screenshot.
3. Optional screen metadata.
4. Previous actions.

Select exactly one next action.

Return only valid JSON.

Never invent coordinates outside the image.

If the task is complete, return finish.

If the task cannot continue, return fail.
```

Then provide the exact action schema.

Keep this prompt provider-neutral.

---

# 32. Model Output Validation

Never trust raw model output.

Pipeline:

```text
raw output
    ↓
extract structured response
    ↓
JSON parse
    ↓
schema validation
    ↓
coordinate validation
    ↓
policy validation
    ↓
execution
```

If validation fails:

```text
retry with repair prompt
```

Limit repair attempts.

Never execute unvalidated text.

---

# 33. Reliability

Implement retry behavior only where appropriate.

Examples:

```text
network failures
rate limiting
provider 5xx
temporary screenshot failure
```

Do NOT blindly repeat computer actions after an uncertain executor failure.

A duplicated click can be dangerous.

Distinguish:

```text
safe retry
```

from:

```text
unsafe retry
```

---

# 34. Loop Detection

Detect obvious stuck behavior.

Examples:

```text
same click repeatedly
same screenshot repeatedly
repeated failed action
alternating between two actions
```

Generate an event such as:

```text
runtime.loop_detected
```

Possible response:

```text
ask model to reassess
```

or:

```text
terminate after threshold
```

---

# 35. Screenshot Similarity

Create an interface allowing detection of whether the screen materially changed after an action.

Potential implementation:

```text
perceptual hash
```

or another lightweight image similarity method.

Do not make heavyweight ML dependencies mandatory.

Use it to detect situations like:

```text
model clicked wrong location
screen did not change
```

---

# 36. Success Verification

Do not assume that:

```text
model says "done"
```

means the task actually succeeded.

Design optional verifiers.

Examples:

```text
screen_contains_text

url_equals

window_exists

DOM_contains

custom callback
```

Later support VLM-based verification.

---

# 37. Human-in-the-Loop

Runtime should eventually support:

```text
approve
deny
edit action
take over
resume
```

Create clean interfaces now.

For CLI:

```text
Proposed action:

CLICK
x: 920
y: 430

[A] Approve
[D] Deny
[E] Edit
```

Do not require confirmation for every action by default.

Only use according to policy configuration.

---

# 38. Doctor Command

Implement:

```bash
vlmux doctor
```

It should report:

```text
VLMux version

Operating system

Python version

Screen capture
✓

Mouse control
✓

Keyboard control
✓

Browser integration
✓ / unavailable

Configured models

Ollama
✓ connected

OpenRouter
✗ API key missing
```

This is important for developer usability.

---

# 39. README

Create a professional README.

Top section:

```text
# VLMux

Give any vision-language model a computer.

One computer-use runtime for:

OpenAI • Gemini • Claude • OpenRouter • Ollama •
vLLM • llama.cpp • custom vision models
```

Then:

```text
model
   ↓
VLMux
   ↓
browser / desktop
```

README sections:

```text
Why VLMux?

Quick Start

How It Works

Supported Models

Supported Platforms

CLI

MCP

Architecture

Safety

Benchmarks

Roadmap

Contributing

License
```

Do not exaggerate features that are not implemented.

Use labels:

```text
✅ Available
🚧 Experimental
🗓 Planned
```

---

# 40. First Working Demo

The first milestone should prove only this:

```text
User
  ↓
CLI task
  ↓
Ollama/OpenAI-compatible VLM
  ↓
Screenshot
  ↓
JSON action
  ↓
Action validation
  ↓
Desktop executor
  ↓
New screenshot
  ↓
loop
```

Example command:

```bash
vlmux run \
  --model ollama/qwen-vl \
  "Open calculator and calculate 23 * 47"
```

Do NOT attempt every advanced feature before this works reliably.

---

# 41. Development Phases

Follow this order.

## Phase 0 — Repository Foundation

Create:

```text
project structure

pyproject.toml

linting

formatting

typing

tests

CI

README skeleton

LICENSE

CONTRIBUTING

SECURITY
```

Use:

```text
ruff
mypy or pyright
pytest
```

Choose one type checker and configure it properly.

---

# Phase 1 — Core Protocol

Implement:

```text
Task

Observation

Screen

Window

Action

ActionResult

AgentContext

ModelDecision
```

Create JSON schemas.

Write unit tests.

No OS control yet.

---

# Phase 2 — Screen + Desktop Executor

Implement:

```text
screenshot

click

double-click

type

hotkey

scroll

wait
```

Add tests where possible.

Provide:

```bash
vlmux screenshot
```

and:

```bash
vlmux doctor
```

---

# Phase 3 — Generic VLM Adapter

Implement:

```text
OpenAI-compatible API adapter
```

Support image input and strict structured output.

Then add:

```text
OpenRouter

Ollama
```

without duplicating architecture.

---

# Phase 4 — Runtime Loop

Connect:

```text
task
observation
model
action
policy
executor
memory
```

Support:

```text
max_steps

timeout

failure handling

finish
```

At this point the calculator demo should work.

---

# Phase 5 — CLI Polish

Support:

```text
vlmux run
vlmux models
vlmux doctor
vlmux observe
vlmux screenshot
vlmux config
```

Use Rich for readable output.

---

# Phase 6 — Set-of-Marks

Introduce interactive-element annotations.

Start simple.

Do NOT require a heavyweight object detection model unless necessary.

Provide extension interfaces.

---

# Phase 7 — Browser Mode

Add:

```text
CDP

DOM inspection

interactive elements

semantic clicking

browser navigation
```

Preference:

```text
DOM
>
A11Y
>
pixel
```

---

# Phase 8 — MCP

Expose runtime and primitive computer tools.

Use the exact same protocol classes.

---

# Phase 9 — Replay + Benchmarking

Create:

```text
task recording

replay

benchmark format

benchmark runner

result reports
```

---

# Phase 10 — Cross-Platform Hardening

Complete reliable:

```text
Windows

macOS

Linux
```

platform backends.

Do not claim a platform as supported until basic tests pass.

---

# 42. Coding Standards

Follow these rules throughout the repository.

1. Use type annotations.

2. Prefer small composable classes.

3. Avoid giant service classes.

4. Avoid global mutable state.

5. Use dependency injection where appropriate.

6. Async for model/network operations.

7. Keep platform-specific code isolated.

8. Never execute unvalidated model output.

9. Never expose API keys.

10. Write meaningful errors.

11. Every major public class/function requires documentation.

12. Every bug fix should ideally include a regression test.

13. Keep dependencies minimal.

14. Do not introduce a framework when a small abstraction is sufficient.

15. Avoid premature microservices.

VLMux should initially run as one local application.

---

# 43. Error Design

Create clear errors such as:

```text
ModelConnectionError

ModelResponseError

ActionValidationError

ActionExecutionError

PolicyViolationError

ScreenCaptureError

UnsupportedPlatformError

ConfigurationError

MaximumStepsExceeded
```

Do not expose large raw stack traces to normal CLI users.

Debug mode may show them.

---

# 44. Security

Assume screenshots may contain secrets.

Never upload data anywhere except to the configured model provider.

Document this clearly.

Local provider mode should be capable of remaining completely local.

Example:

```bash
vlmux run \
  --model ollama/qwen-vl \
  --offline \
  "..."
```

Offline mode should reject remote provider usage.

---

# 45. Privacy Modes

Design future support for:

```text
screen masking

blur regions

exclude applications

exclude monitors

OCR redaction
```

Architecture should allow preprocessors:

```text
raw screenshot
      ↓
ScreenshotProcessor[]
      ↓
model screenshot
```

---

# 46. Plugin Architecture

Do not over-engineer plugins initially.

But define interfaces so external packages can eventually register:

```text
ModelAdapter

Executor

Observer

PolicyRule

Verifier

ScreenshotProcessor
```

Possible future entry-point based loading should not require changes to the runtime.

---

# 47. Repository Quality

This should look like a serious open-source engineering project.

Include:

```text
CI

issue templates

PR template

security policy

contribution guide

architecture documentation

examples

unit tests

integration tests

typed code

release workflow
```

Avoid adding files only for appearances.

Every file should provide value.

---

# 48. GitHub Actions

Create CI for:

```text
Linux

lint

format check

type check

unit tests
```

Later add:

```text
Windows

macOS
```

when OS executor coverage exists.

Do not attempt graphical desktop tests in ordinary headless CI unless properly designed.

---

# 49. Versioning

Use semantic versioning.

Initial:

```text
0.1.0
```

Until the public protocol becomes stable.

Protocol versions must be explicit:

```text
VAP/1.0
```

so clients can remain compatible as VLMux evolves.

---

# 50. Important Architectural Rule

Never build this:

```python
if model == "openai":
    ...
elif model == "gemini":
    ...
elif model == "ollama":
    ...
```

throughout the application.

Provider-specific behavior belongs exclusively inside adapters.

Likewise, do not spread:

```python
if platform.system() == ...
```

through the runtime.

Platform-specific behavior belongs inside executors/providers.

---

# 51. Major Long-Term Differentiator

VLMux should eventually answer:

> Which vision model is actually best at using a computer?

The benchmark framework should allow the same task to run against different models.

Example:

```bash
vlmux benchmark \
  --model openrouter/model-a \
  --model ollama/model-b \
  benchmarks/desktop-basic
```

Output could eventually resemble:

```text
Model        Success     Steps     Latency     Cost
---------------------------------------------------
Model A      18/20       7.4       11.2s       $0.03
Model B      15/20       9.8       28.4s       local
```

Do not create arbitrary rankings from tiny benchmark samples.

Present raw reproducible measurements.

---

# 52. Developer Experience

Installation should eventually be:

```bash
pip install vlmux
```

Then:

```bash
vlmux doctor
```

Then:

```bash
vlmux run \
  --model ollama/qwen-vl \
  "Open Calculator and calculate 100 / 4"
```

Aim for this simplicity.

Internally the architecture can be sophisticated.

Externally the experience must be simple.

---

# 53. Naming

Project:

```text
VLMux
```

Meaning:

```text
Vision-Language Model Multiplexer
```

Core action protocol:

```text
VAP
VLMux Action Protocol
```

Potential Python package:

```text
vlmux
```

CLI:

```text
vlmux
```

MCP server:

```text
vlmux-mcp
```

TypeScript package eventually:

```text
@vlmux/sdk
```

Avoid unnecessarily creating different brands for every component.

---

# 54. Branding

Suggested tagline:

> **Give any vision-language model a computer.**

Technical description:

> **VLMux is a model-agnostic computer-use runtime that connects vision-language models and agent harnesses to browsers and desktop environments through a common perception and action protocol.**

Alternative short description:

> **One computer-use runtime. Any VLM. Any harness.**

---

# 55. What NOT to Build Yet

Do NOT start by building:

```text
web dashboard

mobile app

cloud hosting

distributed agents

agent marketplace

multi-agent orchestration

complex workflow designer

vector database

RAG system

accounts/authentication

billing

SaaS infrastructure
```

These distract from the core problem.

First make:

```text
SEE → DECIDE → ACT → VERIFY
```

work exceptionally well.

---

# 56. First Acceptance Test

VLMux v0.1 is successful when this workflow works:

```bash
vlmux run \
  --model <configured-vision-model> \
  "Open Calculator and calculate 1729 multiplied by 47"
```

VLMux must:

1. Capture the screen.

2. Send the screenshot and task to the model.

3. Receive a structured action.

4. Validate the action.

5. Execute the action.

6. Capture a new observation.

7. Continue until the task is complete.

8. Return a structured result.

9. Stop before exceeding configured step limits.

10. Produce a useful execution trace.

The expected arithmetic result is:

```text
81263
```

---

# 57. Second Acceptance Test

Run:

```bash
vlmux run \
  --model <vision-model> \
  "Open a text editor and type: Hello from VLMux"
```

VLMux must successfully:

```text
identify/open editor

focus editable area

type exact text

verify completion
```

---

# 58. Third Acceptance Test

Browser:

```bash
vlmux run \
  --model <vision-model> \
  "Open the browser and navigate to https://github.com"
```

Eventually verify:

```text
current URL == https://github.com/
```

When browser semantic mode exists, use CDP/DOM rather than coordinate clicking where possible.

---

# 59. Documentation During Development

Maintain:

```text
docs/architecture.md
```

Whenever a significant architectural decision changes.

Create an ADR directory if architectural decisions become substantial:

```text
docs/adr/
```

Example:

```text
0001-python-runtime.md
0002-vap-protocol.md
0003-provider-adapters.md
```

Do not generate dozens of trivial ADRs.

---

# 60. How You Should Work on This Repository

Before editing anything:

1. Inspect the current repository.

2. Read existing code and documentation.

3. Identify what is already implemented.

4. Do not overwrite working functionality unnecessarily.

5. Determine the next incomplete development phase.

6. Create a concise implementation plan.

Then implement.

After each meaningful change:

```text
format
lint
type-check
test
```

Fix failures before moving forward.

When you finish a development phase, report:

```text
Implemented

Files changed

Architecture decisions

Tests added

Commands verified

Known limitations

Recommended next phase
```

Never claim a feature works unless it was actually implemented and reasonably verified.

---

# 61. Current Priority

If this repository is empty or nearly empty, begin with:

```text
PHASE 0
Repository Foundation

then

PHASE 1
Protocol and Core Types
```

Do NOT attempt to implement the entire roadmap in one giant unreviewable change.

The first code should establish foundations that the remaining architecture can safely build on.

Create the repository so that VLMux can evolve into a serious open-source project rather than a one-off demonstration.

---

# 62. Final Product Direction

Keep this model in mind throughout development:

```text
                    ┌──────────────────────┐
                    │         VLMs         │
                    │                      │
                    │ OpenAI               │
                    │ Gemini               │
                    │ Claude               │
                    │ OpenRouter           │
                    │ Ollama               │
                    │ vLLM                 │
                    │ llama.cpp            │
                    │ Custom               │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    Model Adapters    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │      VLMux Core      │
                    │                      │
                    │ Runtime              │
                    │ VAP                  │
                    │ Context              │
                    │ Policy               │
                    │ Events               │
                    │ Verification         │
                    └──────────┬───────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
        ┌───────────────────┐     ┌───────────────────┐
        │    Perception     │     │     Executors     │
        │                   │     │                   │
        │ Screenshot        │     │ Desktop           │
        │ OCR               │     │ Browser           │
        │ Set-of-Marks      │     │ Windows           │
        │ Accessibility     │     │ macOS             │
        │ DOM               │     │ Linux             │
        └───────────────────┘     └───────────────────┘
                  │                         │
                  └────────────┬────────────┘
                               │
                               ▼
                         COMPUTER
```

The project succeeds if developers can plug virtually any capable VLM into VLMux without rewriting their computer-control stack.

Build toward that goal.

# START NOW

Inspect the repository.

If the repository has no meaningful implementation, initialize **Phase 0** and **Phase 1**.

Do not jump ahead.

Create a strong, tested foundation first.

At the end of the first implementation pass, provide:

1. repository tree,
2. files created/modified,
3. architectural decisions,
4. tests executed and their results,
5. commands I can run locally,
6. current limitations,
7. exact recommended next implementation step.
