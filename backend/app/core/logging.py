"""Shared logging setup.

Call `configure_logging()` once at startup; use `get_logger(__name__)` everywhere
so extraction and automation emit consistent, traceable logs.
"""
import logging
import os

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
