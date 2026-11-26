"""Rotating file logging, so a failure leaves something to read."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILENAME = "anki-scribe.log"
LOGGER_NAME = "anki_scribe"
MAX_BYTES = 1_000_000
BACKUPS = 5


def log_path(data_dir: Path) -> Path:
    return Path(data_dir) / LOG_FILENAME


def configure_logging(data_dir: Path) -> Path:
    """Attach a rotating file handler and return the log path."""
    path = log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    # Replace handlers from a previous run so a reload does not duplicate lines.
    for existing in list(logger.handlers):
        logger.removeHandler(existing)

    handler = RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return path
