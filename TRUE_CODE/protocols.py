__author__ = "Nadav"

"""
The protocols.py stores classes being used through the project.
"""

import socket
import hashlib
from hashlib import md5
import random
import pickle
import threading
import struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as PADDING
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.backends import default_backend
import os
from cryptography.hazmat.primitives.asymmetric import dh, rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.serialization import load_pem_parameters, load_pem_public_key
import logging

PEPPER = "Aurex"

class PROTO:
    def log(self, dirct, data):
        try:
            data = data.decode()
        except Exception as e:
            if data[:5] != b'GETKY':  # raise exception but only if received bytes after the encryption stage
                self.Print("the data received is in bytes", 50)
            data = data[:6].decode() + data[6:].hex()  # query| + data in hex
        if dirct == '1':
            self.Print("got <<<<< " + data, 20)
        else:
            self.Print("sent >>>>> " + data, 20)

    def __init__(self, who_get, logging_level, tid=None, cln_sock=None):
        self.who_get = who_get
        self.logging_level = logging_level
        self.tid = tid
        if cln_sock is not None:
            self.sock = cln_sock
        else:
            self.sock = socket.socket()
        self.shared_key = None
        self.parameters = None
        self.has_shared_key = False
        self.lock = threading.Lock()
        self.Print = print
        self.logging_level = logging_level

        self.name = ""

    def connect(self, ip, port):
        self.sock.connect((ip, port))

    def send_first_proto_message(self, proto_name):
        msg = f"AVAIL|{proto_name}"
        self.send_one_message(msg.encode(), encryption=False)


    def create_RSA_keys(self, dir_for_keys=None):
        if dir_for_keys is not None:
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

    def get_public_key_RSA(self):
        self.choosed_RSA = True

        pem_public = self.RSA_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem_public

    def set_RSA_public_key(self, bin_data):  # bin data in the pem_public in bytes
        self.RSA_public_key = serialization.load_pem_public_key(bin_data)



    def encrypt_AES_key_by_RSA_public_key(self):
        self.choosed_RSA = True

        self.AES_key = self.generate_AES_key()
        encrypted_key = self.RSA_public_key.encrypt(
            self.AES_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return encrypted_key

    def get_encrypted_AES_key(self, data: bytes):  #data = AES encrypted by RSA public key
        self.choosed_RSA = True

        decrypted_data = self.RSA_private_key.decrypt(
            data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        self.AES_key = decrypted_data

    def get_AES_key(self):
        return self.AES_key

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



    def send_one_message(self, data: bytes, encryption=True):
        if encryption and self.choosed_RSA:
            new_iv = self.generate_iv()
            message = new_iv + self.AES_encrypt(data, self.AES_key, new_iv)
        else:
            message = data

        self.sock.send(struct.pack('!H', len(message)) + message)
        self.log("2", data)

    def recv_one_message(self, encryption=True):
        len_section = self.__recv_amount(2)
        if not len_section:
            return None
        len_int, = struct.unpack('!H', len_section)  # ! for network (big endian)
        data = self.__recv_amount(len_int)

        if len_int != len(data):
            data = b''
        if encryption and self.choosed_DH:
            iv = data[:16]
            shared_key_in_sha256 = hashlib.sha256(self.shared_key).digest()
            data = self.AES_decrypt(data[16:], shared_key_in_sha256, iv)
        if encryption and self.choosed_RSA:
            iv = data[:16]
            data = self.AES_decrypt(data[16:], self.AES_key, iv)

        self.log("1", data)

        return data

    def __recv_amount(self, size):
        buffer = b''
        while size:
            try:
                new_buffer = self.sock.recv(size)
                if not new_buffer:
                    return None
                buffer += new_buffer
                size -= len(new_buffer)
            except:
                break
        return buffer

    def generate_iv(self):
        iv = os.urandom(16)  # 16 bytes for CBC mode
        return iv

    def generate_AES_key(self):
        key = os.urandom(16)
        return key

    def close(self):
        self.Print(f"Closes {self.who_get} socket!", 10)
        self.sock.close()

class RSA_Client:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
    def start(self):
        self.sock.connect((self.ip, self.port))
        self.contant_with_RSA()
        # Now you can use proto to send/receive encrypted messages with the server

    def contant_with_RSA(self):
        """RSA encryption method"""
        msg = b"CRTKY"
        self.PROTO.send_one_message(msg, False)
        ans = self.PROTO.recv_one_message(encryption=False)
        query, value = ans.split(b"|")  # query = GETKY
        if query == b"GETKY":
            self.PROTO.set_RSA_public_key(value)
            msg = b"GETKY|" + self.PROTO.encrypt_AES_key_by_RSA_public_key()
            self.PROTO.send_one_message(msg, False)
            bin_data = self.PROTO.recv_one_message()

    def send_one_message(self, data: bytes, encryption=True):
        if encryption and self.choosed_RSA:
            new_iv = self.generate_iv()
            message = new_iv + self.AES_encrypt(data, self.AES_key, new_iv)
        else:
            message = data

        self.sock.send(struct.pack('!H', len(message)) + message)
        self.log("2", data)

class RSA_Server:
    def __init__(self, ip, port, dir_for_keys=None, Gateway=False):
        self.ip = ip
        self.port = port
        self.dir_for_keys = dir_for_keys
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.ip, self.port))
        self.sock.listen(5 if not Gateway else 10)
    def start(self):
        while True:
            self.client_sock, addr = self.sock.accept()
            t = threading.Thread(target=self.handle_client, daemon=True, args=(self.client_sock,))
            t.start()

    def handle_client(self, client_socket):
        proto = PROTO(who_get="Server", logging_level=logging.DEBUG, cln_sock=client_socket)
        self.contact_with_RSA()
        # Now you can use proto to send/receive encrypted messages with the client
        
    def contact_with_RSA(self):
        bin_data =  self.PROTO.recv_one_message(False)
        if bin_data == b"CRTKY":
            """ if not exist RSA keys, create new ones and send the public key to the client"""
            self.PROTO.create_RSA_keys()
            msg = b"GETKY|" + self.PROTO.get_public_key_RSA()
            self.PROTO.send_one_message(msg, False)
            bin_data =  self.PROTO.recv_one_message(False)
            query = bin_data[:5]
            encrypted_key = bin_data[6:]
            if query == b"GETKY":
                self.PROTO.get_encrypted_AES_key(encrypted_key)
                self.PROTO.send_one_message(b"ANSOK|yes")

    def send_one_message(self, data: bytes, encryption=True):
        if encryption and self.choosed_RSA:
            new_iv = self.generate_iv()
            message = new_iv + self.AES_encrypt(data, self.AES_key, new_iv)
        else:
            message = data

        self.sock.send(struct.pack('!H', len(message)) + message)
        self.log("2", data)

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
        self.Print = print

    def run(self):
        try:
            self.sock.bind((self.ip, self.port))
            while True:
                bin_data, addr = self.sock.recvfrom(1024)
                if bin_data == b"WHRSV":
                    self.Print(f"got a message from {addr}", 20)
                    self.sock.sendto(self.message_to_send, addr)
                    self.Print(f"sent a message to {addr}", 20)
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
        self.Print = print

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
    
#____________________________________________________

class HTTPSServer:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port

    def start(self):
        pass


class HTTPSClient:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port

    def send_request(self, request):
        pass