# Contributing

Use Python 3.12 or newer and install the development dependencies with
`python -m pip install -e ".[dev]"` inside a virtual environment.

Before submitting a change, run `ruff format --check .`, `ruff check .`, `mypy src`, and `pytest`.
Keep changes focused, add behavior-oriented tests, and do not weaken validation or safety checks.
Generated schemas must be refreshed with `python scripts/export_schemas.py` after protocol changes.

By contributing, you agree that your work may be distributed under the MIT License. Repository
maintenance and final review are handled by [MohamedRF](https://github.com/MohamedRF).
