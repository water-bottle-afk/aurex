"""
Protocol helpers for Aurex blockchain networking.
Length-prefixed JSON (2-byte big-endian) is used for gateway RPC.
"""

from __future__ import annotations

import json
import struct


class Protocol:
    """Socket helpers for length-prefixed JSON payloads."""

    @staticmethod
    def send_lp_json(sock, obj) -> None:
        raw = json.dumps(obj).encode()
        sock.send(struct.pack(">H", len(raw)) + raw)

    @staticmethod
    def recv_lp_json(sock, max_size: int = 65536):
        try:
            len_buf = sock.recv(2)
            if len(len_buf) < 2:
                return None
            (size,) = struct.unpack(">H", len_buf)
            if size > max_size:
                return None
            data = b""
            while len(data) < size:
                chunk = sock.recv(min(size - len(data), 4096))
                if not chunk:
                    return None
                data += chunk
            return json.loads(data.decode())
        except Exception:
            return None

    @staticmethod
    def send_to(host: str, port: int, obj, timeout: float = 3.0, expect_reply: bool = False):
        """Send a length-prefixed JSON payload to host:port. Optionally read reply."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, int(port)))
            Protocol.send_lp_json(sock, obj)
            if expect_reply:
                return Protocol.recv_lp_json(sock)
            return None
        finally:
            try:
                sock.close()
            except Exception:
                pass
