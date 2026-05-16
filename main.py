from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import flet as ft

from Client.client import main as client_main
from Server.server_module import ServerUpdated

SERVER_IP = "localhost"
BACKEND_PORT = 23456

logger = logging.getLogger("aurex")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S")


def _start_backend_server_once() -> None:
    if os.getenv("AUREX_START_BACKEND", "1") != "1":
        return
    server = ServerUpdated(
        host=os.getenv("AUREX_SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("AUREX_SERVER_PORT", str(BACKEND_PORT))),
    )
    threading.Thread(target=server.start, daemon=True).start()


if __name__ == "__main__":
    logger.info("[aurex] launching Flet app...")
    os.environ.setdefault("AUREX_SERVER_HOST", SERVER_IP)
    os.environ.setdefault("AUREX_SERVER_PORT", str(BACKEND_PORT))
    _start_backend_server_once()
    assets_dir = Path(__file__).resolve().parent / "assets"
    ft.app(target=client_main, view=ft.AppView.FLET_APP, assets_dir=str(assets_dir))
