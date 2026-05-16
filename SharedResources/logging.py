"""Shared simple logger wrapper for Aurex."""

from __future__ import annotations

import logging
from pathlib import Path


class Logger:
    """Project logger with debug/info/error helpers."""

    _configured = False

    def __init__(self, file_name: str):
        self.file_name = Path(file_name).name
        if not Logger._configured:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",datefmt="%H:%M:%S")
            Logger._configured = True
        self._logger = logging.getLogger(self.file_name)

    def debug(self, message: str):
        self._logger.debug(message)

    def info(self, message: str):
        self._logger.info(message)

    def error(self, message: str):
        self._logger.error(message)
