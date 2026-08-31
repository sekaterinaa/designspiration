#!/usr/bin/env python3
"""Entry point: python run.py"""

from __future__ import annotations

import logging
import sys

from pnlbot.config import ConfigError, load_config
from pnlbot.bot import run


def main() -> int:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    logging.info("Starting bot (model=%s, db=%s)", config.model, config.db_path)
    run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
