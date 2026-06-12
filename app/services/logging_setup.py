from __future__ import annotations

import logging
import sys


def setup_logging(level: str | int = 'INFO') -> None:
    if isinstance(level, str):
        level_value = getattr(logging, level.strip().upper(), logging.INFO)
    else:
        level_value = int(level)
    root = logging.getLogger()
    root.setLevel(level_value)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level_value)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s'))
    root.addHandler(handler)
