__author__ = "Nadav Cohen"

"""
The classes.py stores classes being used through the project.
"""

import socket
import threading
import struct
import logging


class PROTO:
    # Known binary prefixes — logged as <binary N bytes> without crashing.
    _BINARY_PREFIXES = (
        b"\xff\xd8",   # JPEG
        b"\x89PNG",   # PNG
    )

    def log(self, dirct, data):
        try:
            decoded = data.decode()
            if decoded.startswith("UPLOAD_CHUNK|"):
                parts = decoded.split("|", 4)
                if len(parts) >= 4:
                    decoded = f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}|<chunk>"
            elif decoded.startswith("UPLOAD_INIT|"):
                decoded = "UPLOAD_INIT|<payload>"
            data = decoded
        except Exception:
            # Binary frame — check for known image signatures first so we
            # don't try to decode raw JPEG/PNG bytes (0xff / 0x89 are not
            # valid UTF-8 start bytes and would raise a UnicodeDecodeError).
            if any(data.startswith(sig) for sig in self._BINARY_PREFIXES):
                data = f"<binary image {len(data)} bytes>"
            elif data[:5] == b'GETKY':
                data = data[:6].hex() + data[6:].hex()
            else:
                # Safe hex fallback — never call .decode() on unknown binary.
                data = f"<binary {len(data)} bytes> [{data[:8].hex()}...]"
        if dirct == '1':
            self.Print("got <<<<< " + data, 10)
        else:
            self.Print("sent >>>>> " + data, 10)

    def __init__(self, who_get, logging_level, tid=None, cln_sock=None):
        self.who_get = who_get
        self.logging_level = logging_level
        self.tid = tid
        if cln_sock is not None:
            self.sock = cln_sock
        else:
            self.sock = socket.socket()
        self.lock = threading.Lock()
        self.logger = CustomLogger(f"PROTO for: {self.who_get}", logging_level)
        self.Print = self.logger.Print
        self.logging_level = logging_level

        self.name = ""

    def connect(self, ip, port):
        self.sock.connect((ip, port))

    def send_one_message(self, data: bytes, encryption=False):
        """Send message with 4-byte length prefix (TLS handles encryption)"""
        message = data
        with self.lock:
            self.sock.send(struct.pack('!I', len(message)) + message)
        self.log("2", data)

    def recv_one_message(self, encryption=False):
        """Receive message with 4-byte length prefix (TLS handles decryption)"""
        len_section = self.__recv_amount(4)
        if not len_section:
            return None
        len_int, = struct.unpack('!I', len_section)
        data = self.__recv_amount(len_int)

        if len_int != len(data):
            data = b''

        self.log("1", data)
        return data

    def __recv_amount(self, size):
        buffer = b''
        while size:
            try:
                new_buffer = self.sock.recv(size)
                if not new_buffer:
                    # Socket closed by peer
                    return buffer if buffer else None
                buffer += new_buffer
                size -= len(new_buffer)
            except socket.timeout:
                # Timeout - return what we have so far
                return buffer if buffer else None
            except Exception as e:
                # Other socket errors
                self.Print(f"Socket receive error: {e}", 40)
                return buffer if buffer else None
        return buffer

    def close(self):
        self.Print(f"Closes {self.who_get} socket!", 10)
        self.sock.close()


class ColoredFormatter(logging.Formatter):
    """
    A custom formatter that adds color to log messages based on their level.
    """
    # Define ANSI escape codes for colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[0m'

    def format(self, record):
        log_message = super().format(record)

        if record.levelno == logging.WARNING:
            return f"{self.YELLOW}{log_message}{self.WHITE}"
        elif record.levelno in (logging.ERROR, logging.CRITICAL):
            return f"{self.RED}{log_message}{self.WHITE}"
        elif record.levelno == logging.INFO:
            return f"{self.CYAN}{log_message}{self.WHITE}"
        elif record.levelno == logging.DEBUG:
            return f"{self.GREEN}{log_message}{self.WHITE}"
        else:
            return log_message


class CustomLogger:
    def __init__(self, name, logging_level=logging.DEBUG):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging_level)
        self.logger.propagate = False

        # Only add handler if none exist
        if not self.logger.handlers:
            ch = logging.StreamHandler() # output direction: console
            ch.setLevel(logging_level)

            colored_formatter = ColoredFormatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
            ch.setFormatter(colored_formatter)
            self.logger.addHandler(ch)

        self.dict_of_logs = {
            10: self.logger.debug,
            20: self.logger.info,
            30: self.logger.warning,
            40: self.logger.error,
            50: self.logger.critical
        }

    def Print(self, msg, level):  # instead of print()
        self.dict_of_logs[level](msg)
