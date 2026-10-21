import logging
import sys
from typing import Optional

from core.config import LOG_LEVEL


def setup_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Khởi tạo và cấu hình Logger chuẩn cho toàn bộ dự án.
    Đảm bảo format đồng nhất: timestamp [LEVEL] [logger_name]: message
    """
    logger_name = name or "deputy_profiling"
    logger = logging.getLogger(logger_name)
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    # Đảm bảo root logger hoặc logger hiện tại có stream handler với format chuẩn
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(level)

    return logger
