from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from flet_pages.app import AurexFletApp
else:
    from .app import AurexFletApp


def main(page: ft.Page) -> None:
    app = AurexFletApp(page)
    app.start()


if __name__ == "__main__":
    ft.app(
        target=main,
        view=ft.AppView.WEB_BROWSER,
        host=os.getenv("AUREX_FLET_HOST", "0.0.0.0"),
        port=int(os.getenv("AUREX_FLET_PORT", "8555")),
    )
