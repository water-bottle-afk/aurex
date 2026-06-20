"""Shared colored logger wrapper for Aurex.

Keeps all project output readable:
  - sent/recv lines get a yellow address prefix
  - WARNING is orange, ERROR/CRITICAL is red
  - Flet's internal chatter is silenced completely
"""
from __future__ import annotations

__author__ = "Nadav"

import logging
from pathlib import Path

YELLOW  = "\033[33m"
CYAN    = "\033[36m"
ORANGE  = "\033[38;5;208m"
RED     = "\033[31m"
RESET   = "\033[0m"

LEVEL_COLORS = {
    logging.WARNING:  ORANGE,
    logging.ERROR:    RED,
    logging.CRITICAL: RED,
}

FLET_NOISE_PREFIXES = (
    "flet_core", "flet", "asyncio", "websockets", "websocket",
    "urllib3", "urllib", "httpx", "_client", "hpack",
)

# Content patterns that identify Flet internal chatter regardless of logger name
FLET_NOISE_FRAGMENTS = (
    "trigger event",
    "page(",
    "applifecyclestate",
    "on_keyboard_event",
    "on_scroll",
    "on_resize",
    "on_window",
    "pageviewmodel",
    "controlviewmodel",
    "heartbeat",
    "ws_connect",
    "ws_send",
)


class NoiseFilter(logging.Filter):
    """Block Flet internal messages via both logger name and message content."""

    def filter(self, record: logging.LogRecord) -> bool:
        name_lower = record.name.lower()
        if any(name_lower.startswith(p) for p in FLET_NOISE_PREFIXES):
            return False
        msg_lower = record.getMessage().lower()
        if any(fragment in msg_lower for fragment in FLET_NOISE_FRAGMENTS):
            return False
        return True


class ColoredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        msg_lower = msg.lower()

        is_sent = "sent to" in msg_lower
        is_recv = "recv from" in msg_lower

        if is_sent or is_recv:
            sep = ">>>" if is_sent else "<<<"
            asctime = self.formatTime(record, self.datefmt)
            if sep in msg:
                addr_part, _, rest = msg.partition(sep)
                # Only addr_part is yellow; separator and payload stay default
                return f"{asctime} {YELLOW}{addr_part.rstrip()}{RESET} {sep}{rest}"
            # No separator — colour just the address line
            return f"{asctime} {YELLOW}{msg}{RESET}"

        formatted = super().format(record)
        color = LEVEL_COLORS.get(record.levelno)
        if color:
            return f"{color}{formatted}{RESET}"
        return formatted


class Logger:
    """Project logger: partial yellow for sent/recv, orange WARNING, red ERROR, Flet suppressed."""

    configured = False
    level = logging.DEBUG

    def __init__(self, file_name: str):
        self.file_name = Path(file_name).name
        if not Logger.configured:
            Logger.configure()
        self.logger = logging.getLogger(self.file_name)

    @classmethod
    def configure(cls):
        handler = logging.StreamHandler()
        handler.setFormatter(ColoredFormatter(
            fmt="%(asctime)s %(message)s",
            datefmt="%H:%M:%S",
        ))
        handler.addFilter(NoiseFilter())
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(cls.level)
        # Belt-and-suspenders: also suppress known Flet loggers directly
        for name in FLET_NOISE_PREFIXES:
            logging.getLogger(name).setLevel(logging.CRITICAL + 1)
        cls.configured = True

    @classmethod
    def set_level(cls, level_str: str):
        level = getattr(logging, level_str.upper(), logging.DEBUG)
        cls.level = level
        if cls.configured:
            logging.getLogger().setLevel(level)

    def debug(self, message: str, **kwargs):
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        self.logger.error(message, **kwargs)
