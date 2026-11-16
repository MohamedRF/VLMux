# AGENTS.md — working on VLMux

VLMux is a model-agnostic computer-use runtime (Python, src/vlmux). Keep the
core provider-independent: models propose VAP actions, the policy engine
gates them, executors perform them.

## Layout

- `src/vlmux/protocol/` — VAP action models (discriminated union). Regenerate
  schemas after changing them: `python scripts/export_schemas.py`.
- `src/vlmux/perception/` — screen capture, SoM, OCR, a11y window listing,
  and the ref-based accessibility tree (`ui_tree.py`, `windows_uia.py`).
- `src/vlmux/runtime/engine.py` — bounded SEE→DECIDE→VALIDATE→ACT loop.
- `src/vlmux/executors/` — platform input drivers (pynput behind an injected
  backend; UIA behind `RefRegistry`/`UITreeProvider`).
- `src/vlmux/cli/`, `src/vlmux/mcp/`, `src/vlmux/server/`, `src/vlmux/sdk.py`
  — agent-facing entry points.
- `skills/vlmux-computer-use/SKILL.md` — the agent-side playbook.

## Gates (must all pass)

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
python scripts/export_schemas.py   # when protocol/core models change
```

## Conventions

- Ref actions and anything driven by model output must fail closed with
  typed error codes (`vlmux.exceptions.*.code`), never crash the loop.
- New executor behavior goes behind injected backends so tests never touch
  real input devices.
- See `docs/safety.md` before relaxing any validation or policy.
- Windows-only features import lazily and raise `UnsupportedPlatformError`
  elsewhere.
