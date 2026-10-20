# Contributing

Thanks for helping improve Sovereign Code. It is a small, local-first project —
keep changes focused and honest about what works on a 24 GB Mac.

## Setup

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # tests + ruff
# optional, for sovereign browse:
pip install -e ".[browser]" && playwright install chromium
```

## Checks

```sh
python -m pytest -q   # 96 tests; browser/embedding tests skip when unavailable
ruff check .          # lint
ruff format --check . # formatting
```

## Conventions

- Keep the model catalog honest: only claim a context/role that was actually
  verified on the target hardware.
- New CLI commands get a `sovereign_code/<name>.py` module, a parser entry in
  `cli.py`, tests under `tests/`, and a line in `README.md`.
- Never add network telemetry, CAPTCHA solving, or user-agent spoofing.
- Commit messages are imperative and one line, with a body when needed.

Open a pull request; CI runs `pytest` and `ruff check` automatically.
