"""Entry point: ``python -m procrastination_terminator``."""

from __future__ import annotations

from .bot import run
from .config import Config


def main() -> None:
    run(Config.from_env())


if __name__ == "__main__":
    main()
