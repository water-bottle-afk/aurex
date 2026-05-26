__author__ = "Nadav"

"""
The classes.py stores classes being used through the project.
"""

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

PEPPER = "Aurex"

class Communication:
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
        self.lock = threading.Lock()
        self.logger = Logger(name or __file__)
        self.Print = lambda *args: self.logger.info(" ".join(str(a) for a in args))
        self.name = name
        self.peer_label = peer_label
        self.AES_key = None

        self.user = None
        self.msg_queue: "queue.Queue[object]" = queue.Queue()
        self.send_queue: "queue.Queue[tuple[dict, bool | None] | None]" = queue.Queue()
        self._async_running = False
        self._async_recv_thread = None
        self._async_send_thread = None
        self._async_stop_event = threading.Event()
        self._default_encryption = True
        self._close_marker = object()

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


    def _sanitize_for_log(self, d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if k in ("chunk_b64", "content_b64") and isinstance(v, str) and len(v) > 80:
                out[k] = f"<{len(v)} chars>"
            else:
                out[k] = v
        return out

    def send_one_message(self, data: dict, encryption=True):
        data_json = json.dumps(data, sort_keys=True).encode()

        if encryption:
            new_iv = self.generate_iv()
            message = new_iv + self.AES_encrypt(data_json, self.AES_key, new_iv)
        else:
            message = data_json

        with self.lock:
            self.sock.sendall(struct.pack('!H', len(message)) + message)
        self.log('send', json.dumps(self._sanitize_for_log(data), sort_keys=True))


    def recv_one_message(self, encryption=True):
        len_section = self.__recv_amount(2)
        if not len_section:
            return None
            
        length, = struct.unpack('!H', len_section)
        data = self.__recv_amount(length)

        if not data or len(data) != length:
            return None

        if encryption:
            iv = data[:16]
            data = self.AES_decrypt(data[16:], self.AES_key, iv)

        try:
            decoded = json.loads(data.decode())
            self.log('recv', json.dumps(self._sanitize_for_log(decoded), sort_keys=True))
            return decoded
        except Exception as e:
            self.logger.error(f"Error decoding JSON: {e}")
            return None

    def start_async(self, default_encryption=True):
        """Start duplex queue mode: recv thread -> msg_queue, send_queue -> send thread."""
        if self._async_running:
            return
        self._default_encryption = bool(default_encryption)
        self._async_stop_event.clear()
        self._async_running = True
        self._async_recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._async_send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._async_recv_thread.start()
        self._async_send_thread.start()

    def _recv_loop(self):
        while not self._async_stop_event.is_set():
            msg = self.recv_one_message(encryption=self._default_encryption)
            if msg is None:
                break
            self.msg_queue.put(msg)
        self.msg_queue.put(self._close_marker)
        self._async_running = False

    def _send_loop(self):
        while not self._async_stop_event.is_set():
            item = self.send_queue.get()
            if item is None:
                break
            data, encryption = item
            enc = self._default_encryption if encryption is None else bool(encryption)
            try:
                self.send_one_message(data, encryption=enc)
            except Exception:
                break
        self._async_running = False

    def send_async(self, data: dict, encryption=None):
        if not self._async_running:
            enc = self._default_encryption if encryption is None else bool(encryption)
            self.send_one_message(data, encryption=enc)
            return
        self.send_queue.put((data, encryption))

    def recv_async(self, timeout=None):
        if not self._async_running:
            return self.recv_one_message(encryption=self._default_encryption)
        try:
            return self.msg_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_close_marker(self, value):
        return value is self._close_marker

    def stop_async(self):
        if not self._async_running:
            return
        self._async_stop_event.set()
        try:
            self.send_queue.put_nowait(None)
        except Exception:
            pass

    def __recv_amount(self, size):
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
        """RSA encryption method"""
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



# CLASS UDP CLIENT

class UDPClient:
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

            self.Print(f"UDP client received raw info from {addr}", 20)
            self.Print(bin_data, 10)
            try:
                query, tcp_ip, tcp_port = bin_data.decode().split('|')
                tcp_port = int(tcp_port)
                self.Print(f"Server's At {tcp_ip}:{tcp_port}", 20)
                self.tcp_port = tcp_port
                self.tcp_ip = tcp_ip
                break
            except Exception as e:
                self.Print(f"UDP client Error: {e}", 40)
        self.sock.close()
        return self.tcp_ip, self.tcp_port
    


#-------------------------------------------------------------------


class User:
    """User class with salt + pepper hashing and email verification"""
    
    def __init__(self, username, password, email, salt=None, pubkey=False,
        verification_code=None, reset_time=None, wallet_balance=0.0,):
        self.username = username
        self.email = email
        self.salt = salt if salt else self._create_salt()
        self.password_hash = self._hash_password(password)
        
        self.pubkey = pubkey
        self.verification_code = verification_code
        self.reset_time = reset_time
        self.wallet_balance = float(wallet_balance)
    
    def _create_salt(self):
        """Generate unique salt"""
        num = random.randint(1000000, 9999999)
        return str(num)
    
    def _hash_password(self, password):
        """Hash password with salt + pepper"""
        combined = PEPPER + password + self.salt
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def verify_password(self, password):
        """Verify password matches hash"""
        return self.password_hash == self._hash_password(password)
    
    def set_verification_code(self, code):
        """Set email verification code"""
        self.verification_code = code
    
    def set_reset_time(self, time):
        """Set code expiration time"""
        self.reset_time = time
    
    def is_code_match_and_available(self, current_time, code_to_check):
        """Check if code matches and hasn't expired"""
        if self.verification_code == code_to_check and self.reset_time:
            return current_time < datetime.fromisoformat(self.reset_time)
        return False

    def set_password(self, new_password):
        """Update password hash (e.g. after password reset)."""
        self.password_hash = self._hash_password(new_password)

    def __repr__(self):
        return f"User(username={self.username}, email={self.email}, has_keys={self.has_keys})"

    
@dataclass
class Transaction:
    sender: str
    receiver: str
    amount: float
    signature: str
    timestamp: float

@dataclass
class Block:
    index: int
    prev_hash: str
    transaction: Transaction
    nonce: int
    timestamp: float = time.time()

    def compute_hash(self):
        block_string = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()
