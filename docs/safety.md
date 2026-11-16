# Safety

Model output is untrusted. The execution pipeline is:

```text
HTTP response → JSON extraction → VAP schema → coordinate mapping → bounds → policy → executor
```

Malformed output and out-of-image coordinates can receive only the configured bounded repair
attempts. Normal CLI output does not include provider response bodies or authorization values.

The local policy engine classifies actions into four risk levels:

| Risk | Actions |
| --- | --- |
| `safe` | Most coordinate/ref actions, typing, scrolling, waiting. |
| `sensitive` | Pasting with clipboard text. |
| `external_side_effect` | Launching applications (`open_app`), navigating the signed-in browser (`browser_navigate`). |
| `destructive` | Closing windows (`close_window`) and dangerous hotkey combos (`alt+f4`, `ctrl+w`, `ctrl+shift+w`, `win+r`, `win+l`, `cmd+q`, ...). |

`sensitive`, `external_side_effect`, and `destructive` require human confirmation by default.
TOML configuration can change confirmation and deny sets using `safe`, `sensitive`,
`external_side_effect`, and `destructive` risk names. A deny decision cannot be overridden by the
confirmation callback.

Dry-run captures the screen, calls the model, and validates one proposed action without creating a
desktop executor or executing input. `--offline` allows only localhost model URLs. This protects
against accidental remote screenshot upload, but it does not sandbox the configured local model.

## HTTP API

`vlmux serve` exposes the runtime over HTTP. By default it binds to `127.0.0.1` and still
restricts requests to a loopback `Host` header, which blocks browser-based cross-origin calls.
Set `VLMUX_API_TOKEN` or pass `--token` to require `Authorization: Bearer <token>` on every
request; a token is always required for a non-loopback bind. Requests are capped at 1 MiB.
Treat a configured token as a credential — anyone holding it can drive the computer.
