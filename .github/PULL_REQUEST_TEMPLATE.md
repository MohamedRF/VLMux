## Summary

Describe the behavior changed and why.

## Validation

- [ ] `ruff format --check .`
- [ ] `ruff check .`
- [ ] `mypy src tests`
- [ ] `pytest`

## Safety checklist

- [ ] Model output remains validated before execution.
- [ ] No credentials, screenshots, or sensitive traces are committed or logged.
- [ ] Tests do not move real input devices or depend on a graphical CI session.
