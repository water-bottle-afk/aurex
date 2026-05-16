"""Flet monitoring dashboard for the Aurex gateway."""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from datetime import datetime

import flet as ft


class GatewayGUIBridge:
    """Thread-safe event bridge from gateway worker threads to dashboard UI."""

    def __init__(self):
        self.events: queue.Queue[dict] = queue.Queue()

    def log_event(self, node_id, message, event_type="log", direction="system", status="info", **extra):
        event = {
            "timestamp": extra.pop("timestamp", datetime.now().strftime("%H:%M:%S")),
            "node_id": node_id or "gateway",
            "message": message,
            "event_type": event_type,
            "direction": direction,
            "status": status,
            "tx_id": extra.pop("tx_id", ""),
            "address": extra.pop("address", ""),
        }
        event.update(extra)
        self.events.put(event)


class GatewayLogHandler(logging.Handler):
    """Reflect gateway logger output into the GUI bridge."""

    def __init__(self, bridge: GatewayGUIBridge):
        super().__init__()
        self.bridge = bridge

    def emit(self, record):
        message = self.format(record)
        level = "error" if record.levelno >= logging.ERROR else ("warning" if record.levelno >= logging.WARNING else "info")
        self.bridge.log_event(
            node_id="gateway",
            message=message,
            event_type="log",
            direction="system",
            status=level,
        )


class GatewayDashboard:
    def __init__(self, gateway_server):
        self.gateway_server = gateway_server
        self.bridge = GatewayGUIBridge()
        self.gateway_server.gui_bridge = self.bridge

        self.stop_event = threading.Event()
        self.log_history: list[dict] = []
        self.nodes: dict[str, str] = {}
        self.current_filter = "all"
        self.node_list = None
        self.log_box = None

        self.log_handler = GatewayLogHandler(self.bridge)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger("gateway").addHandler(self.log_handler)

    def _render_event_line(self, event: dict) -> str:
        ts = event.get("timestamp", "")
        node = event.get("node_id", "gateway")
        msg = event.get("message", "")
        tx_id = event.get("tx_id", "")
        if tx_id:
            msg = f"{msg} | tx={tx_id}"
        return f"[{ts}] {node}: {msg}"

    def _build_node_controls(self):
        controls = [
            ft.Container(
                content=ft.Text("all", color=ft.Colors.WHITE),
                bgcolor=ft.Colors.BLUE_700 if self.current_filter == "all" else ft.Colors.BLUE_GREY_900,
                padding=8,
                border_radius=8,
                on_click=lambda e: self._set_filter("all", e.page),
            )
        ]
        for node_id, addr in sorted(self.nodes.items()):
            controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(node_id, color=ft.Colors.WHITE, size=13),
                            ft.Text(addr, color=ft.Colors.BLUE_GREY_200, size=11),
                        ],
                        spacing=2,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.BLUE_700 if self.current_filter == node_id else ft.Colors.BLUE_GREY_900,
                    padding=8,
                    border_radius=8,
                    on_click=lambda e, n=node_id: self._set_filter(n, e.page),
                )
            )
        return controls

    def _set_filter(self, node_id: str, page: ft.Page):
        self.current_filter = node_id
        self._refresh_ui(page)

    def _refresh_ui(self, page: ft.Page):
        if self.current_filter == "all":
            selected = self.log_history
        else:
            selected = [e for e in self.log_history if e.get("node_id") == self.current_filter]

        if self.log_box is not None:
            self.log_box.value = "\n".join(self._render_event_line(event) for event in selected)
        if self.node_list is not None:
            self.node_list.controls = self._build_node_controls()
        page.update()

    def _pump_events(self, page: ft.Page):
        while not self.stop_event.is_set():
            dirty = False
            while True:
                try:
                    event = self.bridge.events.get_nowait()
                except queue.Empty:
                    break

                dirty = True
                self.log_history.append(event)
                node_id = event.get("node_id", "")
                if node_id and node_id != "gateway":
                    self.nodes[node_id] = event.get("address") or self.nodes.get(node_id) or "unknown"

            if dirty:
                self._refresh_ui(page)
            time.sleep(0.15)

    def _main(self, page: ft.Page):
        page.title = "Aurex Gateway Dashboard"
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 16
        page.window_width = 1250
        page.window_height = 780

        self.node_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self.log_box = ft.TextField(
            value="",
            multiline=True,
            read_only=True,
            min_lines=30,
            max_lines=30,
            expand=True,
            bgcolor=ft.Colors.BLACK,
            color=ft.Colors.GREEN_100,
            text_size=12,
        )

        page.add(
            ft.Row(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("Gateway Nodes", size=18, weight=ft.FontWeight.BOLD),
                                self.node_list,
                            ],
                            expand=True,
                        ),
                        width=280,
                        padding=12,
                        bgcolor=ft.Colors.BLUE_GREY_900,
                        border_radius=12,
                    ),
                    ft.Container(
                        content=ft.Column(
                                [
                                    ft.Text("Gateway Monitor", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_200),
                                    self.log_box,
                                ],
                                expand=True,
                            ),
                        expand=True,
                        padding=12,
                        bgcolor=ft.Colors.BLUE_GREY_900,
                        border_radius=12,
                    ),
                ],
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

        self._refresh_ui(page)

        threading.Thread(target=self._pump_events, args=(page,), daemon=True).start()

        def on_disconnect(_):
            self.stop_event.set()

        page.on_disconnect = on_disconnect

    def run(self):
        logging.getLogger("flet").setLevel(logging.WARNING)
        logging.getLogger("flet_desktop").setLevel(logging.WARNING)
        assets_dir = Path(__file__).resolve().parent / "_flet_no_assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        ft.app(target=self._main, view=ft.AppView.FLET_APP, assets_dir=str(assets_dir))


def run_dashboard(gateway_server):
    GatewayDashboard(gateway_server).run()


if __name__ == "__main__":
    from Gateway.gateway import GatewayServer

    gateway = GatewayServer()
    threading.Thread(target=gateway.start, daemon=True).start()
    run_dashboard(gateway)
