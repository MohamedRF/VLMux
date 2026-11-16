# Architecture

VLMux is organized around explicit, provider-independent boundaries:

```text
Model Adapter → VAP Action → Policy → Executor → Operating System
      ↓                                          ↑
      └────────── Observation ← Perception ──────┘
```

## Implemented runtime

`vlmux.protocol` owns VAP. Each action is a strict Pydantic model and the `Action` union is
discriminated by `type`. Unknown fields and malformed values are rejected. Ref actions carry a
snapshot-scoped `ref` token instead of pixels: `@<snapshot_id>:e<index>`. Screen-relative
validation is separate because an action cannot know the current display dimensions.

`vlmux.core` owns tasks, observations, model decisions, bounded agent context, action results,
and runtime results. These types contain no provider SDK objects or operating-system APIs.

`vlmux.config` is the sole environment/configuration boundary. It merges values in this order:
CLI overrides, environment, TOML file, defaults. API keys use `SecretStr` and safe output is
redacted, including userinfo embedded in URLs.

`vlmux.perception` defines `ScreenCaptureProvider`. `MSSScreenCaptureProvider` captures raw RGB in
a worker thread, resizes with Pillow, and returns an encoded `ScreenObservation`. Capture backends
and active-window discovery are injected boundaries, so tests require neither a display nor user
input. The Windows active-window helper is isolated from portable capture code.

`vlmux.perception.ui_tree` and `vlmux.perception.windows_uia` implement accessibility-tree
snapshots with stable element refs:

- `WindowsUITreeProvider` walks UI Automation in deterministic depth-first order, keeps only
  on-screen elements, marks the interactive set (Invoke/Toggle/Value/SelectionItem/
  ExpandCollapse patterns or known control types), assigns refs `@<snapshot_id>:e<index>`, and
  stores them in a shared `RefRegistry` together with per-snapshot filter metadata.
- Refs survive process boundaries: snapshots persist to a user-cache directory, and later
  one-shot invocations (`vlmux click @ref`) re-walk the tree and resolve by match key.
- Resolution is fail-closed: `stale_ref` (missing/changed), `ambiguous_target` (ambiguous
  window/element), or `headless_not_supported` (no UIA action pattern). Live COM references are
  created and consumed within one worker thread per call; COM is initialized per thread.

`vlmux.executors` defines `ComputerExecutor`, which owns VAP dispatch and structured action
results (`success`, `error`, machine-readable `error_code`). Unexpected backend exceptions are
caught and reported as failed results rather than reaching the task loop. `WindowsExecutor` runs a
separately injected pynput backend in worker threads, plus the UIA ref actions through the same
registry the observer filled. Platform selection occurs only in the executor factory; unsupported
systems fail explicitly.

`vlmux.models` defines the provider-independent adapter interface, response parsing, generic VLM
prompt, and provider registry. A shared HTTP base owns bounded retries, `Retry-After` handling,
redirect rejection, and client lifecycle; unreachable/invalid endpoints raise sanitized
`ModelConnectionError`s that name the host but never the credentials. OpenAI-compatible
networking is implemented once for hosted and local presets; the Anthropic adapter translates the
same task and observation into native Messages image blocks. Envelope parse failures consume
bounded repair attempts; truncated outputs fail fast with an explicit `max_tokens` error.

`vlmux.runtime` receives an adapter, observer, policy, executor, event bus, and confirmation
callback through dependency injection. It enforces step, time, failure, retry, and repair bounds,
detects action loops, and never executes terminal actions. The final observation rides in
`RuntimeResult.metadata` (image blob stripped) so verifiers can score the run honestly.

`vlmux.policy` classifies actions independently of model claims: `safe`, `sensitive` (paste),
`external_side_effect` (`open_app`, `browser_navigate`), and `destructive` (`close_window`,
dangerous hotkeys such as `alt+f4`, `ctrl+w`, `win+r`, `cmd+q`). The latter three require
confirmation by default. Deny cannot be overridden by the confirmation callback.

`vlmux.events` provides local sync/async callbacks. Subscriber exceptions are logged and isolated
so tracing or disk failures cannot abort a run.

`vlmux.cli` exposes `run`, `snapshot`, `click`, `set-value`, `models`, `observe`, `screenshot`,
`doctor`, `benchmark`, `replay`, and `config` commands. The CLI composition root is the only place
that constructs concrete providers.

## Coordinate contract

VAP coordinate actions use absolute pixels in the source desktop coordinate space; values can be
negative on monitors positioned left of or above the primary display. Ref actions use no pixels at
all.
If a screenshot is resized for model transport, `ScreenObservation.source_width` and
`source_height` preserve that coordinate space. `origin_x` and `origin_y` retain the captured
region's desktop offset. Central transform functions map encoded-image coordinates to native
absolute coordinates and back. Coordinate validation uses the native region. Adapters supporting
normalized coordinates must convert them before creating a VAP action.

## Dependency direction

- Core domain types may depend on VAP types.
- Provider adapters depend on core and VAP, never on executors.
- Executors depend on VAP, never on model adapters.
- The runtime receives adapter, observer, policy, and executor interfaces by dependency injection.
- Platform selection lives in one executor factory, not in runtime branches.

## Set-of-Marks

`vlmux.perception.som` defines pluggable `ElementDetector`s. The default `RectangleDetector`
scans for rectangular UI regions with Pillow only. The `SetOfMarksObserver` wraps any observer,
draws numbered red badges, and stores a mark registry in observation metadata. The model may
return `click_mark`; the runtime resolves the mark to coordinates before policy and execution.

## Browser mode

`vlmux.browser` speaks Chrome DevTools Protocol over an injected transport (`CDPTransport`); tests
use fakes, production uses `WebSocketCDPTransport`. `BrowserSession` supports navigate, history
(`back`/`forward` via `Page.getNavigationHistory` + `navigateToHistoryEntry` with the entry's
`id`), reload, semantic `click_element`/`type_into_element` (DOM first), DOM inspection,
interactive element listing, and screenshots with real viewport dimensions. The runtime routes
`browser_*` VAP actions to an optional browser executor.

## MCP, REST, and SDK

`vlmux.mcp` serves JSON-RPC MCP over stdio with lazy component construction; `tools/list` works
headlessly. Ref-based tools mirror the CLI envelope and return typed error codes; `run_task` is
wired to the same bounded runtime. `vlmux.server` serves the same runtime over local HTTP with
bearer-token auth (`VLMUX_API_TOKEN`/`--token`, mandatory off-loopback), loopback `Host`
enforcement, and a 1 MiB request cap. `vlmux.sdk` provides async `VLMux` (agent, with
`confirmation_handler=`) and `Computer` (direct control).

## Replay, benchmarks, and verification

`vlmux.trace.TraceRecorder` writes opt-in run directories with task, steps, events, and
screenshots; `vlmux replay` displays them. `vlmux.benchmark` loads TOML specs with verifier types
and reports raw measurements including token usage and cost (`local` for local models, `unknown`
without configured prices). The runtime threads the final observation into
`RuntimeResult.metadata` so `SpecVerifier` can check the run honestly (`url_equals`,
`screen_contains_text`, ...). A `Verifier` dependency can reject unsubstantiated `finish` claims.

## Cross-platform

`MacOSExecutor` and `LinuxExecutor` share a pynput-backed POSIX base and differ only in
application launching (`open -a ... [--args]` / direct exec). Capture is MSS-based everywhere;
Windows adds active-window capture and UIA ref snapshots. `focus_window` and `close_window`
dispatch through the base executor with explicit unsupported errors on platforms without window
management backends.
