import logging
from typing import Optional


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("enterprise_knowledge_copilot")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = configure_logging()
