from __future__ import annotations

import logging
import os
import sys


DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)s [%(name)s] %(message)s'


def setup_logging() -> None:
    """集中化日志配置。

    生产环境建议通过 LOG_LEVEL=INFO/WARNING/ERROR 控制级别；
    Docker 默认输出到 stdout，交给容器日志收集/轮转。
    """
    level_name = (os.getenv('LOG_LEVEL') or 'INFO').strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=os.getenv('LOG_FORMAT') or DEFAULT_LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
