from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft

sys.path.insert(0, str(Path(__file__).resolve().parent))
from Client.app import AurexFletApp


def main(page: ft.Page) -> None:
    import traceback
    try:
        print("[aurex] main() called, building app...")
        app = AurexFletApp(page)
        print("[aurex] AurexFletApp created, calling start()...")
        app.start()
        print("[aurex] start() returned OK")
    except Exception as exc:
        traceback.print_exc()
        page.add(ft.Text(f"STARTUP ERROR: {exc}", color="red", size=16))
        page.update()


if __name__ == "__main__":
    print("[aurex] launching Flet web app...")
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        host=os.getenv("AUREX_FLET_HOST", "10.100.102.58"),
        port=int(os.getenv("AUREX_FLET_PORT", "8555")),
        assets_dir="assets",
    )
