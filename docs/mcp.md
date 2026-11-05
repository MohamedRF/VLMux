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
| `computer.click` / `computer.double_click` | Click at absolute coordinates |
| `computer.type` | Type text into the focused control |
| `computer.hotkey` | Press a keyboard shortcut |
| `computer.scroll` / `computer.drag` / `computer.wait` | Pointer and timing primitives |
| `computer.windows` | List executor-visible windows |
| `computer.open_app` | Launch an application (shell-free) |
| `computer.run_task` | Full task through the configured VLM |

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
