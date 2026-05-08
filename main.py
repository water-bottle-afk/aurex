from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import flet as ft
import uvicorn

from aurex_logging import AurexLogger

SERVER_IP = "localhost"
#SERVER_IP = "nadav.cohen"
BACKEND_PORT = 23456
FLET_PORT = 8550

sys.path.insert(0, str(Path(__file__).resolve().parent))
from Client.app import AurexFletApp
from Server.server_module import Server

logger = AurexLogger.get_logger(__name__)


def main(page: ft.Page) -> None:
    try:
        logger.info("[aurex] main() called, building app...")
        app = AurexFletApp(page)
        logger.info("[aurex] AurexFletApp created, calling start()...")
        app.start()
        logger.info("[aurex] start() returned OK")
    except Exception as exc:
        logger.exception("Startup error")
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


def _start_backend_server_once() -> None:
    if os.getenv("AUREX_START_BACKEND", "1") != "1":
        return
    server = Server(
        host=os.getenv("AUREX_SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("AUREX_SERVER_PORT", str(BACKEND_PORT))),
    )
    threading.Thread(target=server.start, daemon=True).start()


def _resolve_tls_path(env_name: str, default_relative: str) -> Path:
    raw_value = os.getenv(env_name, default_relative).strip()
    path = Path(raw_value)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parent / path).resolve()
    return path


if __name__ == "__main__":
    _suppress_disconnect_noise()
    logger.info("[aurex] launching Flet web app...")
    os.environ.setdefault("AUREX_SERVER_HOST", SERVER_IP)
    os.environ.setdefault("AUREX_SERVER_PORT", str(BACKEND_PORT))
    _start_backend_server_once()
    if not os.getenv("FLET_SECRET_KEY"):
        os.environ["FLET_SECRET_KEY"] = "dev-secret-change-me"
    _upload_dir = Path(__file__).resolve().parent / "uploads"
    _upload_dir.mkdir(exist_ok=True)
    flet_host = os.getenv("AUREX_FLET_HOST", SERVER_IP)
    flet_port = int(os.getenv("AUREX_FLET_PORT", str(FLET_PORT)))
    cert_path = _resolve_tls_path("AUREX_FLET_CERT_FILE", "HTTPS/server.crt")
    key_path = _resolve_tls_path("AUREX_FLET_KEY_FILE", "HTTPS/server.key")
    if not cert_path.exists() or not key_path.exists():
        raise FileNotFoundError(
            f"Missing Flet TLS files: cert={cert_path} key={key_path}"
        )

    asgi_app = ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        assets_dir="assets",
        upload_dir=str(_upload_dir),
        export_asgi_app=True,
    )
    logger.info("[aurex] Flet HTTPS URL: https://%s:%s/", flet_host, flet_port)
    uvicorn.run(
        asgi_app,
        host=flet_host,
        port=flet_port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
