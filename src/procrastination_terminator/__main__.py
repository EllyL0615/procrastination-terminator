"""Entry point: ``python -m procrastination_terminator``."""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from .bot import run
from .config import Config


def main() -> None:
    load_dotenv()  # load .env from the working directory into os.environ, if present
    argv = sys.argv[1:]
    if argv and argv[0] == "init-notion":
        from .notion_init import init_notion

        init_notion(argv[1:])
        return
    run(Config.from_env())


if __name__ == "__main__":
    main()
