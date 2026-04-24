__author__ = "Nadav Cohen"

"""Transport and logging utilities used by the server runtime."""

import asyncio
import sys
from pathlib import Path

try:
    from aurex_logging import AurexLogger
    from protocol_definitions import UPLOAD_CHUNK_PREFIX
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from aurex_logging import AurexLogger
    from protocol_definitions import UPLOAD_CHUNK_PREFIX
from websockets.exceptions import ConnectionClosed


class PROTO:
    logger = AurexLogger.get_logger(__name__)

    # Keep logs readable: these frames are expected binary payloads, not text commands.
    _BINARY_PREFIXES = (
        b"\xff\xd8",   # JPEG
        b"\x89PNG",   # PNG
    )

    def log(self, direction, data):
        try:
            decoded = data.decode()
            if decoded.startswith(UPLOAD_CHUNK_PREFIX.decode("utf-8")):
                parts = decoded.split("|", 4)
                if len(parts) >= 4:
                    decoded = f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}|<chunk>"
            elif decoded.startswith("UPLOAD_INIT|"):
                decoded = "UPLOAD_INIT|<payload>"
            data = decoded
        except Exception:
            # Avoid decoding unknown bytes; keep enough context for debugging.
            if any(data.startswith(sig) for sig in self._BINARY_PREFIXES):
                data = f"<binary image {len(data)} bytes>"
            elif data[:5] == b'GETKY':
                data = data[:6].hex() + data[6:].hex()
            else:
                data = f"<binary {len(data)} bytes> [{data[:8].hex()}...]"
        if direction == '1':
            self.logger.debug("got <<<<< %s", data)
        else:
            self.logger.debug("sent >>>>> %s", data)

    def __init__(self, tid=None, cln_sock=None, loop=None):
        self.tid = tid
        self.sock = cln_sock
        self.loop = loop
        self._async_send_lock = None
        self.name = ""

    def _coerce_payload(self, data: bytes):
        if isinstance(data, str):
            return data
        if data.startswith(UPLOAD_CHUNK_PREFIX):
            return data
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data

    async def _send_payload(self, payload):
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")
        if self._async_send_lock is None:
            self._async_send_lock = asyncio.Lock()
        async with self._async_send_lock:
            await self.sock.send(payload)

    async def async_send_one_message(self, data: bytes, encryption=False):
        """Send a full WebSocket frame."""
        payload = self._coerce_payload(data)
        await self._send_payload(payload)
        self.log("2", data)

    def send_one_message(self, data: bytes, encryption=False):
        """Send a full WebSocket frame from non-async code."""
        if self.loop is None:
            raise RuntimeError("WebSocket loop is not configured")
        future = asyncio.run_coroutine_threadsafe(
            self.async_send_one_message(data, encryption=encryption),
            self.loop,
        )
        future.result()

    async def async_recv_one_message(self, encryption=False):
        """Receive a full WebSocket frame."""
        if self.sock is None:
            return None
        try:
            payload = await self.sock.recv()
        except ConnectionClosed:
            return None
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.log("1", data)
        return data

    def recv_one_message(self, encryption=False):
        """Receive a full WebSocket frame from non-async code."""
        if self.loop is None:
            raise RuntimeError("WebSocket loop is not configured")
        future = asyncio.run_coroutine_threadsafe(
            self.async_recv_one_message(encryption=encryption),
            self.loop,
        )
        return future.result()

    def close(self):
        self.logger.debug("Closes socket")
