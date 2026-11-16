# MCP Server

VLMux exposes computer capabilities over the Model Context Protocol (MCP) on
stdio, using the exact same runtime, executor, and observer as the CLI.

## Start

```bash
vlmux mcp
# or
vlmux-mcp
```

## Tools

| Tool | Description |
|---|---|
| `computer.observe` | Screen observation (metadata; image redacted) |
| `computer.screenshot` | Screen observation with base64 image |
| `desktop_snapshot` | Accessibility tree with element refs (Windows; requires `vlmux[uia]`) |
| `desktop_click` | Invoke an accessibility-tree element by ref (headless) |
| `desktop_set_value` | Set an accessibility-tree element's value by ref (headless) |
| `computer.click` / `computer.double_click` | Click at absolute coordinates |
| `computer.type` | Type text into the focused control |
| `computer.hotkey` | Press a keyboard shortcut |
| `computer.scroll` / `computer.drag` / `computer.wait` | Pointer and timing primitives (`wait` capped at 300000 ms) |
| `computer.windows` | List executor-visible windows |
| `computer.open_app` | Launch an application (shell-free) |
| `computer.run_task` | Full task through the configured VLM |

`desktop_snapshot` arguments: `{"app": "Calculator"}`, `{"window_id": "725198"}`,
`{"interactive_only": true, "max_elements": 500}`. Refs returned by the snapshot belong to that
snapshot; re-snapshot when a ref action fails with `stale_ref`. See [a11y-refs.md](a11y-refs.md).

`computer.run_task` arguments:

```json
{
  "task": "Open Chrome and search for VLMux",
  "model": "openrouter/google/gemini-2.5-pro",
  "max_steps": 20
}
```

Low-level tools never contact a model; `run_task` uses the same bounded
runtime loop as `vlmux run` (policy, loop detection, and step limits apply).
Tool errors are returned as `isError: true` with a JSON body carrying `code`
where applicable; protocol-level failures use JSON-RPC error codes (`-32601`
unknown method, `-32602` invalid params, `-32700` parse error).
