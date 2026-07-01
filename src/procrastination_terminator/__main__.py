"""Entry point: ``python -m procrastination_terminator``."""

from __future__ import annotations

from dotenv import load_dotenv

from .bot import run
from .config import Config


def main() -> None:
    load_dotenv()  # load .env from the working directory into os.environ, if present
    run(Config.from_env())


if __name__ == "__main__":
    main()
