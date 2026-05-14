from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft


def _bootstrap_imports() -> Path:
    client_dir = Path(__file__).resolve().parent
    project_root = client_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return project_root


PROJECT_ROOT = _bootstrap_imports()

from aurex_logging import AurexLogger
from Client.app import AurexFletApp

logger = AurexLogger.get_logger(__name__)


def main(page: ft.Page) -> None:
    try:
        app = AurexFletApp(page)
        app.start()
    except Exception as exc:
        logger.exception("Desktop startup error")
        page.add(ft.Text(f"STARTUP ERROR: {exc}", color="red", size=16))
        page.update()


if __name__ == "__main__":
    os.environ.setdefault("AUREX_SERVER_HOST", "localhost")
    os.environ.setdefault("AUREX_SERVER_PORT", "23456")

    upload_dir = PROJECT_ROOT / "uploads"
    upload_dir.mkdir(exist_ok=True)

    logger.info("[aurex] launching desktop app...")
    ft.app(
        target=main,
        view=ft.AppView.FLET_APP,
        assets_dir=str(PROJECT_ROOT / "assets"),
        upload_dir=str(upload_dir),
    )

