# Replay and Benchmarks

## Replay

Trace recording is opt-in. Enable it in configuration:

```toml
[runtime]
record_runs = true
runs_dir = "runs"
```

Each run writes `runs/<timestamp>/` containing:

```text
task.json        task definition
steps.jsonl      one record per step (decision, result, screenshot file)
events.jsonl     runtime events
screenshots/     001.png, 002.png, ...
```

Screenshots may contain secrets. Treat trace directories accordingly and
never commit them.

```bash
vlmux replay RUN_ID
```

## Benchmarks

Benchmark specs are TOML documents in a directory:

```toml
name = "calculator_multiplication"
task = "Open Calculator and calculate 1729 multiplied by 47"
max_steps = 20

[success]
type = "screen_contains_text"
value = "81263"
```

Verifier types: `screen_contains_text`, `url_equals`, `window_exists`,
`dom_contains_text`, `always_true`.

```bash
vlmux benchmark benchmarks --model ollama/qwen3-vl --model openrouter/google/gemini-2.5-pro
```

Output reports raw reproducible measurements (success, steps, latency, token
usage, cost). Local models report cost as `local`; without configured
per-token prices, hosted models report `unknown`. VLMux never fabricates
rankings from small samples.
