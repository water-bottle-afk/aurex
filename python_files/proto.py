"""
PROTO class for handling message communication over TLS.
Implements the communication protocol for the Blockchain system.
"""

import socket
import ssl
import struct
import threading
import logging


class PROTO:
    """
    Protocol handler for sending and receiving messages over TLS.
    Handles message framing with length prefix (2 bytes).
    """
    
    def __init__(self, who_get, logging_level, tid=None, cln_sock=None):
        """
        Initialize PROTO instance.
        
        Args:
            who_get: Identifier for logging purposes
            logging_level: Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL)
            tid: Thread ID for server instances
            cln_sock: Existing client socket (for server use)
        """
        self.who_get = who_get
        self.logging_level = logging_level
        self.tid = tid
        
        if cln_sock is not None:
            self.sock = cln_sock
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        self.lock = threading.Lock()
        self.logger = self._setup_logger(who_get, logging_level)
        self.Print = self._print_message
        
    def _setup_logger(self, name, logging_level):
        """Setup logger with appropriate handlers."""
        logger = logging.getLogger(name)
        logger.setLevel(logging_level)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging_level)
            formatter = logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _print_message(self, msg, level):
        """Print message using logger."""
        level_map = {
            10: self.logger.debug,
            20: self.logger.info,
            30: self.logger.warning,
            40: self.logger.error,
            50: self.logger.critical
        }
        log_func = level_map.get(level, self.logger.info)
        log_func(msg)
    
    def _log_message(self, direction, data):
        """Log sent or received messages."""
        try:
            decoded_data = data.decode('utf-8')
        except Exception:
            # If can't decode, show as hex
            if len(data) >= 5:
                decoded_data = data[:5].decode('utf-8', errors='ignore') + ' | ' + data[5:].hex()
            else:
                decoded_data = data.hex()
        
        if direction == 'recv':
            self.Print(f"Received <<<<< {decoded_data}", 20)
        else:
            self.Print(f"Sent >>>>> {decoded_data}", 20)
    
    def connect(self, ip, port, use_tls=True):
        """
        Connect to server with optional TLS.
        
        Args:
            ip: Server IP address
            port: Server port
            use_tls: Whether to use TLS (default True)
        """
        try:
            self.sock.connect((ip, port))
            
            if use_tls:
                # Wrap socket with TLS
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE  # For self-signed certificates
                
                self.sock = context.wrap_socket(self.sock, server_hostname=ip)
                self.Print(f"TLS connection established to {ip}:{port}", 20)
            else:
                self.Print(f"Connected to {ip}:{port} (non-TLS)", 20)
                
        except Exception as e:
            self.Print(f"Connection failed: {e}", 40)
            raise
    
    def send_one_message(self, data, encryption=True):
        """
        Send a message with 2-byte length prefix.
        
        Args:
            data: Message as bytes
            encryption: Parameter kept for compatibility (TLS handles encryption)
        """
        try:
            with self.lock:
                # Create message with length prefix
                message = struct.pack('!H', len(data)) + data
                self.sock.sendall(message)
                self._log_message('send', data)
        except Exception as e:
            self.Print(f"Error sending message: {e}", 40)
            raise
    
    def recv_one_message(self, encryption=True):
        """
        Receive a message with 2-byte length prefix.
        
        Args:
            encryption: Parameter kept for compatibility (TLS handles encryption)
            
        Returns:
            Message as bytes or None if connection closed
        """
        try:
            self.Print(f"⏳ Waiting to receive message length header...", 20)
            
            # Receive length header (2 bytes)
            len_data = self._recv_exact(2)
            if not len_data:
                self.Print("❌ Connection closed by remote host (no length data)", 20)
                return None
            
            # Unpack message length
            msg_len, = struct.unpack('!H', len_data)
            self.Print(f"📊 Message length: {msg_len} bytes", 20)
            
            # Receive message
            message = self._recv_exact(msg_len)
            if not message:
                self.Print("❌ Connection closed while receiving message", 20)
                return None
            
            self._log_message('recv', message)
            return message
            
        except Exception as e:
            self.Print(f"❌ Error receiving message: {e}", 40)
            return None
    
    def _recv_exact(self, num_bytes):
        """
        Receive exact number of bytes.
        
        Args:
            num_bytes: Number of bytes to receive
            
        Returns:
            Bytes received or empty bytes if connection closed
        """
        buffer = b''
        remaining = num_bytes
        
        self.Print(f"🔄 _recv_exact: waiting for {num_bytes} bytes", 10)
        
        while remaining > 0:
            try:
                self.Print(f"   Calling sock.recv({remaining})...", 10)
                chunk = self.sock.recv(remaining)
                
                if not chunk:
                    self.Print(f"   ❌ sock.recv returned empty (socket closed), got {len(buffer)}/{num_bytes} bytes", 40)
                    return buffer if buffer else None
                
                self.Print(f"   ✅ Received {len(chunk)} bytes", 10)
                buffer += chunk
                remaining -= len(chunk)
            except Exception as e:
                self.Print(f"   ❌ Error in _recv_exact: {e}", 40)
                return None
        
        self.Print(f"✅ _recv_exact completed: got {len(buffer)} bytes", 10)
        return buffer
    
    def close(self):
        """Close the socket connection."""
        try:
            self.Print(f"Closing connection for {self.who_get}", 10)
            self.sock.close()
        except Exception as e:
            self.Print(f"Error closing socket: {e}", 40) 