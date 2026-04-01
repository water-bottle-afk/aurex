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


def _suppress_disconnect_noise() -> None:
    """Silence the benign ClientDisconnected / InvalidState tracebacks that
    uvicorn/starlette print every time a browser tab closes normally."""
    import logging
    for name in ("uvicorn.error", "uvicorn.access", "uvicorn.protocols.websockets"):
        log = logging.getLogger(name)
        log.addFilter(
            type(
                "_DisconnectFilter",
                (logging.Filter,),
                {
                    "filter": staticmethod(
                        lambda r: "ClientDisconnected" not in r.getMessage()
                        and "InvalidState" not in r.getMessage()
                    )
                },
            )()
        )


if __name__ == "__main__":
    _suppress_disconnect_noise()
    print("[aurex] launching Flet web app...")
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        host=os.getenv("AUREX_FLET_HOST", "10.100.102.58"),
        port=int(os.getenv("AUREX_FLET_PORT", "8555")),
        assets_dir="assets",
    )
