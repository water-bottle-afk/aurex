"""Tkinter monitoring dashboard for the Aurex blockchain gateway."""

from __future__ import annotations

import logging
import queue
import re
import threading
from datetime import datetime

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - optional dependency
    ctk = None

import tkinter as tk
from tkinter import ttk


HASH_FOUND_RE = re.compile(r"(found(?: the)? hash[:=]\s*)([0-9a-fA-F]+)", re.IGNORECASE)
GENERIC_HASH_RE = re.compile(r"\b0{2,}[0-9a-fA-F]{4,}\b")


class GatewayGUIBridge:
    """Thread-safe event bridge from gateway thread to Tk main thread."""

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
            "hash_value": extra.pop("hash_value", ""),
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
        lower = message.lower()
        direction = "system"
        if "inbound" in lower or "confirmed" in lower:
            direction = "inbound"
        elif "broadcast" in lower or "outbound" in lower:
            direction = "outbound"
        status = "error" if record.levelno >= logging.ERROR else ("warning" if record.levelno >= logging.WARNING else "info")
        self.bridge.log_event("gateway", message, event_type="log", direction=direction, status=status)


class GatewayDashboard:
    def __init__(self):
        self.bridge = GatewayGUIBridge()
        self.stop_event = threading.Event()
        self.server_thread = None
        self.log_history: list[dict] = []
        self.node_rows: dict[str, str] = {}
        self.node_index = 0
        self.current_filter = "all"

        self.root = ctk.CTk() if ctk else tk.Tk()
        if ctk:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("dark-blue")
        self.root.title("Aurex Gateway Dashboard")
        self.root.geometry("1240x760")
        self.root.minsize(920, 560)
        if ctk:
            self.root.configure(fg_color="#111827")
        else:
            self.root.configure(bg="#111827")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_styles()
        self._build_layout()
        self._attach_logger()
        self._start_gateway()
        self.root.after(100, self._poll_events)

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Sidebar.Treeview", background="#172033", fieldbackground="#172033", foreground="#e5e7eb", rowheight=34, borderwidth=0)
        style.configure("Sidebar.Treeview.Heading", background="#0f172a", foreground="#f8fafc", relief="flat")
        style.map("Sidebar.Treeview", background=[("selected", "#1d4ed8")], foreground=[("selected", "#ffffff")])

    def _build_layout(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(self.root, bg="#0f172a", width=320)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        title = tk.Label(sidebar, text="Aurex Gateway Dashboard", bg="#0f172a", fg="#f8fafc", font=("Segoe UI Semibold", 16))
        title.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 8))

        all_button = tk.Button(sidebar, text="All Nodes", command=lambda: self._set_filter("all"), bg="#1d4ed8", fg="white", relief="flat", activebackground="#2563eb", activeforeground="white")
        all_button.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        self.node_tree = ttk.Treeview(sidebar, columns=("node", "endpoint", "status"), show="headings", style="Sidebar.Treeview")
        self.node_tree.heading("node", text="Node")
        self.node_tree.heading("endpoint", text="IP:Port")
        self.node_tree.heading("status", text="Status")
        self.node_tree.column("node", width=90, anchor="w")
        self.node_tree.column("endpoint", width=145, anchor="w")
        self.node_tree.column("status", width=70, anchor="center")
        self.node_tree.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.node_tree.bind("<<TreeviewSelect>>", self._on_node_selected)

        right = tk.Frame(self.root, bg="#111827")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        header = tk.Label(right, text="Gateway Monitor", bg="#111827", fg="#f8fafc", font=("Consolas", 15, "bold"), anchor="w")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))

        terminal_frame = tk.Frame(right, bg="#111827")
        terminal_frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        terminal_frame.grid_columnconfigure(0, weight=1)
        terminal_frame.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            terminal_frame,
            bg="#050816",
            fg="#d1d5db",
            insertbackground="#f8fafc",
            relief="flat",
            wrap="word",
            font=("Consolas", 11),
            state="disabled",
            padx=14,
            pady=14,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(terminal_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        self.log_text.tag_configure("timestamp", foreground="#94a3b8")
        self.log_text.tag_configure("node", foreground="#f8fafc")
        self.log_text.tag_configure("inbound", foreground="#67e8f9")
        self.log_text.tag_configure("outbound", foreground="#facc15")
        self.log_text.tag_configure("system", foreground="#c4b5fd")
        self.log_text.tag_configure("error", foreground="#f87171")
        self.log_text.tag_configure("warning", foreground="#fb923c")
        self.log_text.tag_configure("hash", foreground="#f59e0b")

    def _attach_logger(self):
        handler = GatewayLogHandler(self.bridge)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"))
        gateway_logger = logging.getLogger("gateway_server")
        gateway_logger.addHandler(handler)
        gateway_logger.setLevel(logging.INFO)
        self.log_handler = handler

    def _start_gateway(self):
        import gateway_server
        self.server_thread = threading.Thread(
            target=gateway_server.run_server,
            kwargs={"stop_event": self.stop_event, "gui_bridge": self.bridge},
            daemon=True,
        )
        self.server_thread.start()

    def _poll_events(self):
        dirty = False
        while True:
            try:
                event = self.bridge.events.get_nowait()
            except queue.Empty:
                break
            dirty = True
            self.log_history.append(event)
            self._update_node_sidebar(event)
        if dirty:
            self._render_logs()
        if not self.stop_event.is_set():
            self.root.after(100, self._poll_events)

    def _update_node_sidebar(self, event):
        node_id = event.get("node_id", "")
        if not node_id or node_id == "gateway":
            return
        if node_id not in self.node_rows:
            self.node_index += 1
            self.node_rows[node_id] = f"Node {self.node_index}"
        label = self.node_rows[node_id]
        address = event.get("address") or self._last_value(node_id, "address") or "unknown"
        status = event.get("status", "info")
        if status == "connected":
            status_text = "● Online"
        elif status == "disconnected":
            status_text = "● Offline"
        elif status == "error":
            status_text = "● Error"
        else:
            status_text = "● Active"
        values = (label, address, status_text)
        if self.node_tree.exists(node_id):
            self.node_tree.item(node_id, values=values)
        else:
            self.node_tree.insert("", "end", iid=node_id, values=values)

    def _last_value(self, node_id, key):
        for event in reversed(self.log_history):
            if event.get("node_id") == node_id and event.get(key):
                return event.get(key)
        return ""

    def _on_node_selected(self, _event):
        selected = self.node_tree.selection()
        if selected:
            self._set_filter(selected[0])

    def _set_filter(self, node_id):
        self.current_filter = node_id
        if node_id == "all":
            self.node_tree.selection_remove(self.node_tree.selection())
        self._render_logs()

    def _render_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        for event in self.log_history:
            if self.current_filter != "all" and event.get("node_id") != self.current_filter:
                continue
            self._append_event(event)
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _append_event(self, event):
        timestamp = event.get("timestamp", "")
        node_id = event.get("node_id", "gateway")
        node_label = self.node_rows.get(node_id, node_id.title() if node_id == "gateway" else node_id)
        direction = event.get("direction", "system")
        status = event.get("status", "info")
        message = event.get("message", "")
        tx_id = event.get("tx_id")
        prefix = f"[{timestamp}] {node_label}: "
        if tx_id:
            message = f"{message} | tx={tx_id}"

        self.log_text.insert("end", prefix[: len(f"[{timestamp}] ")], ("timestamp",))
        self.log_text.insert("end", prefix[len(f"[{timestamp}] "):], ("node",))
        message_tag = "error" if status == "error" else ("warning" if status == "warning" else direction)
        self._insert_highlighted_message(message, message_tag)
        self.log_text.insert("end", "\n")

    def _insert_highlighted_message(self, message, message_tag):
        match = HASH_FOUND_RE.search(message)
        if match:
            start, end = match.span(2)
            self.log_text.insert("end", message[:start], (message_tag,))
            self.log_text.insert("end", message[start:end], ("hash",))
            self.log_text.insert("end", message[end:], (message_tag,))
            return
        generic = GENERIC_HASH_RE.search(message)
        if generic:
            start, end = generic.span(0)
            self.log_text.insert("end", message[:start], (message_tag,))
            self.log_text.insert("end", message[start:end], ("hash",))
            self.log_text.insert("end", message[end:], (message_tag,))
            return
        self.log_text.insert("end", message, (message_tag,))

    def _on_close(self):
        self.stop_event.set()
        try:
            logging.getLogger("gateway_server").removeHandler(self.log_handler)
        except Exception:
            pass
        self.root.after(150, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    GatewayDashboard().run()
