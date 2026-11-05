# Architecture

VLMux is organized around explicit, provider-independent boundaries:

```text
Model Adapter → VAP Action → Policy → Executor → Operating System
       ↑                                      ↓
       └──────── Observation ← Perception ────┘
```

## Implemented runtime

`vlmux.protocol` owns VAP 1.0. Each action is a strict Pydantic model and the `Action` union is
discriminated by `type`. Unknown fields and malformed values are rejected. Screen-relative
validation is separate because an action cannot know the current display dimensions.

`vlmux.core` owns tasks, observations, model decisions, bounded agent context, action results,
and runtime results. These types contain no provider SDK objects or operating-system APIs.

`vlmux.config` is the sole environment/configuration boundary. It merges values in this order:
CLI overrides, environment, TOML file, defaults. API keys use `SecretStr` and safe output is
redacted.

`vlmux.perception` defines `ScreenCaptureProvider`. `MSSScreenCaptureProvider` captures raw RGB in
a worker thread, resizes with Pillow, and returns an encoded `ScreenObservation`. Capture backends
and active-window discovery are injected boundaries, so tests require neither a display nor user
input. The Windows active-window helper is isolated from portable capture code.

`vlmux.executors` defines `ComputerExecutor`, which owns VAP dispatch and structured action
results. `WindowsExecutor` runs a separately injected pynput backend in worker threads. Platform
selection occurs only in the executor factory. Unsupported systems fail explicitly rather than
pretending to execute input.

`vlmux.models` defines the provider-independent adapter interface, response parsing, generic VLM
prompt, and provider registry. A shared HTTP base owns bounded retries, sanitized failures, and
client lifecycle. OpenAI-compatible networking is implemented once for hosted and local presets;
the Anthropic adapter translates the same task and observation into native Messages image blocks.
Provider selection remains confined to the registry and does not leak into the runtime.

`vlmux.runtime` receives an adapter, observer, policy, executor, event bus, and confirmation
callback through dependency injection. It enforces step, time, failure, retry, and repair bounds.
Terminal actions never reach the OS executor, dry-run stops after one validated proposal, and
failed input actions are never blindly repeated by the executor.

`vlmux.policy` classifies actions independently of model claims. `vlmux.events` provides local
sync/async callbacks without distributed infrastructure.

`vlmux.cli` exposes working `run`, `models`, `observe`, `screenshot`, `doctor`, and `config`
commands. The CLI composition root is the only place that constructs concrete providers.

## Coordinate contract

VAP coordinate actions use absolute pixels in the source desktop coordinate space; values can be
negative on monitors positioned left of or above the primary display.
If a screenshot is resized for model transport, `ScreenObservation.source_width` and
`source_height` preserve that coordinate space. `origin_x` and `origin_y` retain the captured
region's desktop offset. Central transform functions map encoded-image coordinates to native
absolute coordinates and back. Coordinate validation uses the native region. Adapters supporting
normalized coordinates must convert them before creating a VAP action.

## Dependency direction

- Core domain types may depend on VAP types.
- Provider adapters will depend on core and VAP, never on executors.
- Executors will depend on VAP, never on model adapters.
- The runtime will receive adapter, observer, policy, and executor interfaces by dependency
  injection.
- Platform selection will live in one executor factory, not in runtime branches.

## Set-of-Marks (Phase 6)

`vlmux.perception.som` defines pluggable `ElementDetector`s. The default
`RectangleDetector` scans for rectangular UI regions with Pillow only. The
`SetOfMarksObserver` wraps any observer, draws numbered red badges, and
stores a mark registry in observation metadata. The model may return
`click_mark`; the runtime resolves the mark to coordinates before policy and
execution. DOM detectors can supply elements through the same protocol.

## Browser mode (Phase 7)

`vlmux.browser` speaks Chrome DevTools Protocol over an injected transport
(`CDPTransport`); tests use fakes, production uses `WebSocketCDPTransport`.
`BrowserSession` supports navigate, history, reload, semantic
`click_element`/`type_into_element` (DOM first), DOM inspection, interactive
element listing, and screenshots. The runtime routes `browser_*` VAP actions
to an optional browser executor and never falls back to coordinates when a
semantic action is available and fails.

## MCP, REST, and SDK (Phase 8)

`vlmux.mcp` serves JSON-RPC MCP over stdio with `computer.*` tools backed by
the same executor/observer as the CLI; `computer.run_task` reuses the runtime.
`vlmux.server` serves the same runtime over local HTTP (`POST /v1/tasks`,
`GET /v1/tasks/:id`, `GET /v1/observe`, `GET /health`). `vlmux.sdk`
provides async `VLMux` (agent) and `Computer` (direct control) classes.

## Replay, benchmarks, and verification (Phase 9)

`vlmux.trace.TraceRecorder` writes opt-in run directories with task, steps,
events, and screenshots; `vlmux replay` displays them. `vlmux.benchmark`
loads TOML specs with verifier types (`screen_contains_text`, `url_equals`,
`window_exists`, `dom_contains_text`, `always_true`) and reports raw
measurements including token usage and cost (`local` for local models,
`unknown` without configured prices). The runtime aggregates usage into
`RuntimeResult.metadata`, detects repeated action loops (`runtime.loop_detected`),
and emits perceptual-hash screen-change signals (`runtime.screen_unchanged`).
A `Verifier` dependency can reject unsubstantiated `finish` claims.

## Cross-platform (Phase 10)

`MacOSExecutor` and `LinuxExecutor` share a pynput-backed POSIX base and
differ only in application launching (`open -a` / direct exec). Capture is
MSS-based everywhere; Windows adds active-window capture. `focus_window` and
`close_window` dispatch through the base executor with explicit
unsupported errors on platforms without window management backends.

## Implemented phases

Phases 0–10 are implemented; see the README status table for the
implemented/experimental distinction of each surface.
