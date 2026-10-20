"""Allow `python -m sovereign_code`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
