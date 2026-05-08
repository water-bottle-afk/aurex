from __future__ import annotations

import logging
import os


class AurexLogger:
    _configured = False
    _format = "%(asctime)s | %(filename)s | %(levelname)s | %(message)s"
    _datefmt = "%Y-%m-%d %H:%M:%S"

    @classmethod
    def _env_debug_mode(cls) -> bool:
        raw = os.getenv("AUREX_DEBUG_MODE", os.getenv("DEBUG_MODE", "0")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @classmethod
    def configure(cls, debug_mode: bool | None = None) -> int:
        if debug_mode is None:
            debug_mode = cls._env_debug_mode()
        level = logging.DEBUG if debug_mode else logging.WARNING
        root = logging.getLogger()
        if not root.handlers:
            logging.basicConfig(level=level, format=cls._format, datefmt=cls._datefmt)
        else:
            root.setLevel(level)
            for handler in root.handlers:
                handler.setLevel(level)
                handler.setFormatter(logging.Formatter(fmt=cls._format, datefmt=cls._datefmt))
        cls._configured = True
        # Keep third-party client transport chatter out of normal logs.
        for noisy_name in (
            "flet",
            "flet_core",
            "flet_app",
            "websockets",
            "websockets.client",
            "websockets.server",
            "websockets.protocol",
            "asyncio",
        ):
            logging.getLogger(noisy_name).setLevel(logging.WARNING)
        return level

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        if not cls._configured:
            cls.configure()
        return logging.getLogger(name)
