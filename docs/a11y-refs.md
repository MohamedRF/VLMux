# Accessibility refs (UI-tree mode)

VLMux can see the desktop the way agent-desktop does: not by pixels, but as an
**accessibility tree of ref-tagged elements**. The vision model acts on a ref
like `@s1a2b3:e8`, and VLMux re-locates the live element at action time through
the OS accessibility API — headlessly, without moving the pointer or taking
focus.

## Why refs instead of coordinates

- Pixel coordinates are guesswork (model misclicks, resized screenshots, DPI).
  A ref is a deterministic handle minted during the observation.
- Ref actions invoke the UIA element directly (`Invoke`/`Toggle`/`SelectionItem`),
  which is faster, invisible to other people at the machine, and cannot miss.
- Refs fail loudly: when the UI changes, the stale ref errors out with a typed
  code (`stale_ref`) instead of silently clicking whatever happens to be at
  those pixels now.

## Windows support

UI-tree mode is currently Windows-only (UI Automation). It requires the
optional extra:

```bash
pip install "vlmux[uia]"
```

Then select the mode:

```toml
# config.toml
[runtime]
perception_mode = "ui_tree"
```

or pass it through the SDK/API settings the same way. The screenshot is still
captured (for the model's vision input and for trace/replay), and the compact
element listing is rendered into the prompt under `ui_tree`.

## The loop

```bash
# See the desktop as tokens
vlmux snapshot

#   {"version":"0.2.0","ok":true,"command":"snapshot","data":{...}}
#   elements: [{"role":"button","name":"Save","ref":"@s1a2b3:e8", ...}, ...]

# Act on one element (headless; the mouse does not move)
vlmux click '@s1a2b3:e8'
vlmux set-value '@s1a2b3:e3' 'Ada Lovelace'
vlmux set-value '@s1a2b3:e3' --stdin < secret.txt

# Verify with a fresh snapshot
vlmux snapshot
```

In agent loops (MCP, SDK, or `vlmux run`):

1. The observer captures the screen and registers interactive elements with a
   fresh `snapshot_id`.
2. Refs (`@<snapshot_id>:e<index>`) are handed to the model inside the prompt.
3. The model answers `{"type":"click_ref","ref":"@s1a2b3:e8"}` or
   `{"type":"set_value_ref","ref":"@s1a2b3:e3","value":"..."}`.
4. The executor re-walks the tree and matches on `(role, name, automation_id,
   occurrence)`. Exactly one live match is required, otherwise the action
   fails with `stale_ref` (missing/moved) or `ambiguous_target`
   (multiple matches) instead of clicking the wrong thing.
5. If the model sees `stale_ref`, it takes a fresh observation.

Refs are scoped to their snapshot. A later `vlmux snapshot` mints a new
`snapshot_id`; refs from the previous snapshot become stale by design.

## CLI reference

| Command | Purpose |
| --- | --- |
| `vlmux snapshot [--app TITLE] [--window-id ID] [-i/--all] [--max-elements N]` | Print the accessibility tree as one JSON envelope. Successful responses include `data.snapshot_id` and `data.elements[].ref`. |
| `vlmux click REF [--button left\|middle\|right] [--double]` | Invoke one element. Headless activation supports `left`; other buttons and multi-clicks fail with `headless_not_supported` (use coordinate actions instead). |
| `vlmux set-value REF VALUE` or `vlmux set-value REF --stdin` | Set an editable element's value via the UIA Value pattern. Read-only or pattern-less elements fail with `headless_not_supported`. |

Snapshots persist for a while under the platform user cache directory so a
later one-shot command (`vlmux click '@s1a2b3:e8'`) can resolve refs minted by
`vlmux snapshot`. The registry keeps the last eight snapshots.

Every command prints a single JSON object:

```json
{
  "version": "0.2.0",
  "ok": true,
  "command": "snapshot",
  "data": { "snapshot_id": "s1a2b3", "ref_count": 12, "elements": [...] }
}
```

Errors use `{"ok": false, "error": {"message": "...", "code": "..."}}` with a
machine-readable `code` (`stale_ref`, `ambiguous_target`, `invalid_args`,
`headless_not_supported`, ...), and exits non-zero.

## MCP tools

`vlmux mcp` exposes the same capability:

| Tool | Description |
| --- | --- |
| `desktop_snapshot` | Capture the accessibility tree (`app`, `window_id`, `interactive_only`, `max_elements`). |
| `desktop_click` | Invoke an element by `ref` (headless). |
| `desktop_set_value` | Set an element's value by `ref` (headless). |

Failures come back with `isError: true` and a JSON body containing `code`
(`stale_ref`, `headless_not_supported`, ...).

## Limitations and safety

- Ref actions invoke whatever the accessibility API exposes; they do not move
  the pointer and do not take focus. Physical input still exists via the
  coordinate actions.
- Ref actions currently cannot right/middle-click or double-click headlessly;
  those return `headless_not_supported`.
- Invisible, zero-area, and offscreen elements are excluded from the snapshot.
- Snapshots capture *all* visible top-level windows by default; use
  `--app`/`--window-id` (or `window_id=` in MCP) to narrow scope. Minimizing
  the surface the model sees reduces both token cost and mistakes.
- The policy engine treats ref actions like their coordinate counterparts.
  Sensitive/destructive/external actions still require confirmation per the
  configured policy — see [safety.md](safety.md).
