"""
classes.py — shared data models and networking primitives used across the whole project.

Anything that more than one module needs to import lives here:
  Communication  — encrypted TCP framing (AES-CBC, async queues)
  RSA_Client/Server — RSA key-exchange wrappers
  UDPServer/Client  — broadcast discovery helpers
  Transaction, Block — blockchain data structures
  MarketplaceItem    — the asset record shared by server, gateway, and client
"""
__author__ = "Nadav"

import time
from dataclasses import dataclass, asdict
from datetime import datetime
import socket
import hashlib
import random
import threading
import struct
import queue
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as PADDING
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.backends import default_backend
import os
import json
import base64
from cryptography.hazmat.primitives.asymmetric import dh, rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.serialization import load_pem_parameters, load_pem_public_key

from SharedResources.logging import Logger

class Communication:
    """For recv/sending messages over a socket with optional AES-CBC encryption."""
    def log(self, dirct, data):
        try:
            ip, port = self.sock.getpeername()
            addr = f"{ip}:{port}"
        except Exception:
            addr = "?"
        label = self.peer_label or "Peer"
        if dirct == 'recv':
            self.Print(f"Recv From {label} at {addr} <<< {data}")
        else:
            self.Print(f"Sent to {label} at {addr} >>> {data}")

    def __init__(self, sock, name="", peer_label=""):
        self.sock = sock
        self.shared_key = None
        self.parameters = None
        self.send_lock = threading.Lock()   # guards concurrent sendall calls
        self.recv_lock = threading.Lock()   # guards concurrent recv_one_message calls
        self.lock = self.send_lock          # backward-compat alias
        self.logger = Logger(name or __file__)
        self.Print = lambda *args: self.logger.info(" ".join(str(a) for a in args))
        self.name = name
        self.peer_label = peer_label
        self.AES_key = None

        self.user = None
        self.msg_queue: "queue.Queue[object]" = queue.Queue()
        self.send_queue: "queue.Queue[tuple[dict, bool | None] | None]" = queue.Queue()
        self.async_running = False
        self.async_recv_thread = None
        self.async_send_thread = None
        self.async_stop_event = threading.Event()
        self.default_encryption = True
        self.close_marker = object()

    #used for server's communication
    def set_user(self, user):
        self.user = user
        

    def connect(self, ip, port):
        self.sock.connect((ip, port))

    # Function to encrypt data using AES CBC mode
    def AES_encrypt(self, plaintext: bytes, key: bytes, iv: bytes) -> bytes:
        # Pad the plaintext to block size
        padder = PADDING.PKCS7(AES.block_size).padder()
        padded_plaintext = padder.update(plaintext) + padder.finalize()

        # Create cipher and encrypt
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
        return ciphertext

    # Function to decrypt data using AES CBC mode
    def AES_decrypt(self, ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
        # Create cipher and decrypt
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        # Unpad the plaintext
        unpadder = PADDING.PKCS7(AES.block_size).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
        return plaintext


    def sanitize_for_log(self, d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if k in ("chunk_b64", "content_b64") and isinstance(v, str) and len(v) > 80:
                out[k] = f"<{len(v)} chars>"
            else:
                out[k] = v
        return out

    def send_one_message(self, data: dict, encryption=True):
        """Serialise *data* to JSON, optionally encrypt, and send with a 2-byte length header."""
        data_json = json.dumps(data, sort_keys=True).encode()

        if encryption:
            new_iv = self.generate_iv()
            # prepend IV so the receiver can decrypt without out-of-band state
            message = new_iv + self.AES_encrypt(data_json, self.AES_key, new_iv)
        else:
            message = data_json

        # pack length as big-endian unsigned short then flush the whole thing atomically
        with self.lock:
            self.sock.sendall(struct.pack('!H', len(message)) + message)
        self.log('send', json.dumps(self.sanitize_for_log(data), sort_keys=True))


    def recv_one_message(self, encryption=True):
        """Read the next framed message and return it as a dict (or None on disconnect).

        The recv_lock ensures that if two threads ever call this on the same
        Communication object the length-header + payload bytes won't interleave.
        """
        with self.recv_lock:
            len_section = self.recv_amount(2)
            if not len_section:
                return None

            length, = struct.unpack('!H', len_section)
            data = self.recv_amount(length)

        if not data or len(data) != length:
            return None

        if encryption:
            iv   = data[:16]
            data = self.AES_decrypt(data[16:], self.AES_key, iv)

        try:
            decoded = json.loads(data.decode())
            self.log('recv', json.dumps(self.sanitize_for_log(decoded), sort_keys=True))
            return decoded
        except Exception as e:
            self.logger.error(f"Error decoding JSON: {e}")
            return None

    def start_async(self, default_encryption=True):
        """Switch to duplex queue mode: a background recv thread feeds msg_queue,
        and a background send thread drains send_queue.  Call recv_async / send_async
        after this instead of the blocking one-shot variants."""
        if self.async_running:
            return
        self.default_encryption = bool(default_encryption)
        self.async_stop_event.clear()
        self.async_running = True
        self.async_recv_thread = threading.Thread(target=self.recv_loop, daemon=True)
        self.async_send_thread = threading.Thread(target=self.send_loop, daemon=True)
        self.async_recv_thread.start()
        self.async_send_thread.start()

    def recv_loop(self):
        while not self.async_stop_event.is_set():
            msg = self.recv_one_message(encryption=self.default_encryption)
            if msg is None:
                break
            self.msg_queue.put(msg)
        self.msg_queue.put(self.close_marker)
        self.async_running = False

    def send_loop(self):
        while not self.async_stop_event.is_set():
            item = self.send_queue.get()
            if item is None:
                break
            data, encryption = item
            enc = self.default_encryption if encryption is None else bool(encryption)
            try:
                self.send_one_message(data, encryption=enc)
            except Exception:
                break
        self.async_running = False

    def send_async(self, data: dict, encryption=None):
        if not self.async_running:
            enc = self.default_encryption if encryption is None else bool(encryption)
            self.send_one_message(data, encryption=enc)
            return
        self.send_queue.put((data, encryption))

    def recv_async(self, timeout=None):
        if not self.async_running:
            return self.recv_one_message(encryption=self.default_encryption)
        try:
            return self.msg_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_close_marker(self, value):
        return value is self.close_marker

    def stop_async(self):
        if not self.async_running:
            return
        self.async_stop_event.set()
        try:
            self.send_queue.put_nowait(None)
        except Exception:
            pass

    def recv_amount(self, size):
        buffer = b''
        while size:
            try:
                new_buffer = self.sock.recv(size)
                if not new_buffer:
                    return None
                buffer += new_buffer
                size -= len(new_buffer)
            except ConnectionError:
                return None
        return buffer
    

    @staticmethod
    def generate_iv():
        iv = os.urandom(16)  # 16 bytes for CBC mode
        return iv

    @staticmethod
    def generate_AES_key():
        key = os.urandom(16)
        return key

    def close(self):
        self.stop_async()
        self.Print(f"Closes {self.name} socket!")
        self.sock.close()

class RSA_Client:
    """TCP client that performs an RSA key exchange handshake with the server."""
    def __init__(self, ip, port, name="RSA_Client", peer_label=""):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.communication = Communication(sock=self.sock, name=name, peer_label=peer_label)
        
    def start(self):
        self.sock.connect((self.ip, self.port))
        self.contact_with_RSA()
        # Now you can use proto to send/receive encrypted messages with the server

        self.communicate_with_server()

    def communicate_with_server(self):
        while True:
            msg = input("Enter message to send (or 'exit' to quit): ")
            if msg.lower() == 'exit':
                break
            self.communication.send_one_message({"type": "MESSAGE", "content": msg})
            answer = self.communication.recv_one_message()

        self.communication.close()


    def contact_with_RSA(self):
        """Perform the RSA key-exchange handshake with the server.

        Asks for the server's public key, encrypts a freshly-generated AES key
        with it, sends the encrypted key, and waits for the OK.  After this the
        communication object is ready for AES-encrypted traffic.
        """
        msg = {"type": "SEND_PUBLIC_KEY"}
        self.communication.send_one_message(msg, False)
        answer = self.communication.recv_one_message(encryption=False)

        if answer["type"] == "GET_PUBLIC_KEY":
            server_public_key_pem = base64.b64decode(answer["value"])
            self.RSA_public_key = serialization.load_pem_public_key(server_public_key_pem)

            encrypted_key = self.encrypt_AES_key_by_RSA_public_key()
            msg = {
                "type": "GET_SYMETRIC_KEY",
                "value": base64.b64encode(encrypted_key).decode("ascii"),
            }

            self.communication.send_one_message(msg, False)
            self.communication.AES_key = self.AES_key
            answer = self.communication.recv_one_message()


    def encrypt_AES_key_by_RSA_public_key(self):
        self.AES_key = self.communication.generate_AES_key()
        encrypted_key = self.RSA_public_key.encrypt(
            self.AES_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return encrypted_key

    def get_AES_key(self):
        return self.AES_key

    def close(self):
        self.communication.logger.info("Closes Client socket!")
        self.sock.close()

class RSA_Server:
    
    """TCP server that performs an RSA key exchange handshake with each client"""
    def __init__(self, ip, port, dir_for_keys=None, Gateway=False, name="RSA_Server", peer_label="Peer"):
        self.ip = ip
        self.port = port
        self.name = name
        self.peer_label = peer_label
        self.dir_for_keys = dir_for_keys
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.ip, self.port))
        self.sock.listen(5 if not Gateway else 10)

    def start(self):
        while True:
            self.client_sock, addr = self.sock.accept()
            t = threading.Thread(target=self.communicate_with_client, daemon=True, args=(self.client_sock,))
            t.start()
        

    def communicate_with_client(self, client_socket):
        communication = Communication(client_socket, name=self.name, peer_label=self.peer_label)
        self.contact_with_RSA(communication)
        
        self.handle_client(communication)

    def handle_client(self, communication): #will gonna be ovveridden
        pass
        
    def contact_with_RSA(self, communication):
        answer =  communication.recv_one_message(False)
        if answer is None:
            communication.logger.error("recved none from client, closing connection")
            communication.close()
            return
        if answer["type"] == "SEND_PUBLIC_KEY":
            self.create_RSA_keys(self.dir_for_keys)
            public_key = self.get_public_key_RSA()

            msg = {
                "type": "GET_PUBLIC_KEY",
                "value": base64.b64encode(public_key).decode("ascii"),
            }

            communication.send_one_message(msg, False)
            answer =  communication.recv_one_message(False)
            if answer["type"] == "GET_SYMETRIC_KEY":
                encrypted_key = base64.b64decode(answer["value"])
                self.get_encrypted_AES_key(encrypted_key, communication)
                communication.send_one_message({"type": "OK"})

    
    def create_RSA_keys(self, dir_for_keys="ServerKeys"):
        self.dir_for_keys = dir_for_keys
        if not os.path.exists(dir_for_keys):
            os.makedirs(dir_for_keys)
        private_key_path = os.path.join(dir_for_keys, "private_key.pem")
        public_key_path = os.path.join(dir_for_keys, "public_key.pem")

        if os.path.exists(private_key_path) and os.path.exists(public_key_path):
            with open(private_key_path, "rb") as f:
                self.RSA_private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                )
            with open(public_key_path, "rb") as f:
                self.RSA_public_key = serialization.load_pem_public_key(f.read())
            return
            
        self.RSA_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )

        self.RSA_public_key = self.RSA_private_key.public_key()

        with open(private_key_path, "wb") as f:
            f.write(self.RSA_private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        with open(public_key_path, "wb") as f:
            f.write(self.RSA_public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ))

    def get_public_key_RSA(self):
        pem_public = self.RSA_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem_public

    def set_RSA_public_key(self, bin_data):  # bin data in the pem_public in bytes
        self.RSA_public_key = serialization.load_pem_public_key(bin_data)

    def get_encrypted_AES_key(self, data: bytes, communication):  #data = AES encrypted by RSA public key
        decrypted_data = self.RSA_private_key.decrypt(
            data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        communication.AES_key = decrypted_data


# CLASS UDP SERVER

class UDPServer:
    """For discovery of the gateway by blockchain nodes: listens for "WHRSV" broadcasts and replies with the server's IP/port."""

    def __init__(self, self_ip, self_port, srv_ip, srv_port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ip = self_ip
        self.port = self_port
        self.srv_ip = srv_ip
        self.srv_port = srv_port
        self.message_to_send = f"SRVAT|{srv_ip}|{str(srv_port)}"
        self.message_to_send = self.message_to_send.encode()
        self.logger = Logger(__file__)
        self.Print = lambda *args: self.logger.info(" ".join(str(a) for a in args))

    def run(self):
        try:
            self.sock.bind((self.ip, self.port))
            while True:
                bin_data, addr = self.sock.recvfrom(1024)
                if bin_data == b"WHRSV":
                    self.Print(f"Recv From Bnode at {addr[0]}:{addr[1]} <<< WHRSV")
                    self.sock.sendto(self.message_to_send, addr)
                    self.Print(f"Sent to Bnode at {addr[0]}:{addr[1]} >>> {self.message_to_send.decode()}")
        except OSError as e:
            self.Print(f"CONNECTION ERROR! {e}", 50)
        except Exception as e:
            self.Print(f"ERROR! {e}", 50)




class UDPClient:
    """For discovery of the gateway by blockchain nodes: broadcasts "WHRSV" and waits for the server's reply with its IP/port."""
    def __init__(self, udp_srv_port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # in order to send broadcast msgs (sol -> low level socket, so=socket option, val1  = enable)

        self.udp_srv_port = udp_srv_port
        self.broadcast_ip = "255.255.255.255"
        self.tcp_ip = None
        self.tcp_port = None
        self.logger = Logger(__file__)
        self.Print = lambda *args: self.logger.info(" ".join(str(a) for a in args))

    def run(self):
        while self.tcp_ip is None:
            message = b"WHRSV"
            self.sock.sendto(message, (self.broadcast_ip, self.udp_srv_port))  # broadcast msg
            bin_data, addr = self.sock.recvfrom(1024)

            self.Print(f"UDP client received raw info from {addr}")
            self.Print(bin_data, 10)
            try:
                query, tcp_ip, tcp_port = bin_data.decode().split('|')
                tcp_port = int(tcp_port)
                self.Print(f"Server's At {tcp_ip}:{tcp_port}")
                self.tcp_port = tcp_port
                self.tcp_ip = tcp_ip
                break
            except Exception as e:
                self.Print(f"UDP client Error: {e}")
        self.sock.close()
        return self.tcp_ip, self.tcp_port
    

    
ASSET_STATUS_PENDING  = "PENDING"
ASSET_STATUS_FOR_SALE = "FOR_SALE"
ASSET_STATUS_UNLISTED = "UNLISTED"
ASSET_STATUS_SOLD     = "SOLD"


def migrate_asset_status(raw: dict) -> str:
    """Derive asset_status from old blockchain_status/for_sale fields when upgrading."""
    if "asset_status" in raw:
        return str(raw["asset_status"])
    bc = str(raw.get("blockchain_status", "")).strip().lower()
    fs = bool(raw.get("for_sale", True))
    if bc in ("verified",):
        return ASSET_STATUS_FOR_SALE if fs else ASSET_STATUS_UNLISTED
    return ASSET_STATUS_PENDING


@dataclass
class MarketplaceItem:
    """Marketplace asset — shared between server, gateway, and client."""

    asset_id: str
    owner: str
    asset_name: str
    description: str
    file_type: str
    cost: float
    created_at: str
    storage_path: str = ""
    version: int = 1
    asset_status: str = ASSET_STATUS_PENDING
    public_key: str = ""

    def to_dict(self):
        return {
            "asset_id": self.asset_id,
            "owner": self.owner,
            "asset_name": self.asset_name,
            "description": self.description,
            "file_type": self.file_type,
            "cost": self.cost,
            "storage_path": self.storage_path,
            "created_at": self.created_at,
            "version": self.version,
            "asset_status": self.asset_status,
            "public_key": self.public_key,
        }

    @classmethod
    def from_dict(cls, raw):
        return cls(
            asset_id=str(raw.get("asset_id", "")),
            owner=str(raw.get("owner", "")),
            asset_name=str(raw.get("asset_name", "")),
            description=str(raw.get("description", "")),
            file_type=str(raw.get("file_type", "")),
            cost=float(raw.get("cost", 0.0)),
            storage_path=str(raw.get("storage_path", "")),
            created_at=str(raw.get("created_at", "")),
            version=int(raw.get("version", 1)),
            asset_status=migrate_asset_status(raw),
            public_key=str(raw.get("public_key", "")),
        )

    def __repr__(self):
        return (
            f"MarketplaceItem(asset_id='{self.asset_id}', owner='{self.owner}', "
            f"asset_name='{self.asset_name}', cost={self.cost}, status={self.asset_status})"
        )


@dataclass
class Transaction:
    "Transaction class"
    sender: str
    receiver: str
    amount: float
    signature: str
    timestamp: float

@dataclass
class Block:
    "Block class"
    index: int
    prev_hash: str
    transaction: Transaction
    nonce: int
    timestamp: float = time.time()

    def compute_hash(self):
        block_string = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()
