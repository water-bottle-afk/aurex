__author__ = "Nadav Cohen"

"""
The classes.py stores classes being used through the project.
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
import ssl

PEPPER = "pepper"

# CLASS USER

class User:
    def __init__(self, username, password, email):
        self.username = username
        self.salt = self.create_salt()
        self.password = self.secured_password(password)
        self.email = email
        self.time_of_available_reset = None
        self.verification_code = None

    def create_salt(self):
        num = random.randint(1, 1000000)
        salt = str(num)
        return salt

    def secured_password(self, password):
        new_password = PEPPER + password + self.salt
        return md5(new_password.encode()).hexdigest()

    def get_password(self):
        return self.password

    def set_password(self, other_password):
        self.password = self.secured_password(other_password)

    def get_username(self):
        return self.username

    def get_email(self):
        return self.email

    def get_reset_time(self):
        return self.time_of_available_reset

    def get_verification_code(self):
        return self.verification_code

    def set_reset_time(self, new_time):
        self.time_of_available_reset = new_time

    def set_verification_code(self, new_code):
        self.verification_code = new_code

    def is_code_match_and_available(self, asking_time, verification_code):
        if self.time_to_reset_ok(asking_time) and self.is_verification_code_ok(verification_code):
            if verification_code is not None:
                self.time_of_available_reset = None
                self.verification_code = None
                return True
        return False

    def time_to_reset_ok(self, other_time):
        return self.time_of_available_reset >= other_time

    def is_verification_code_ok(self, other_verification_code):
        return self.verification_code == other_verification_code

    def is_same_password(self, other_password):
        return self.password == self.secured_password(other_password)

    def __repr__(self):
        return f"User: username = {self.username}, password = {self.password}, email = {self.email}"


# CLASS DB

lock = threading.Lock()

USERS_FILE_PATH = "Database/users.pickle"


class DB:
    def __init__(self):
        self.users = {}
        with lock:
            with open(USERS_FILE_PATH, 'rb') as file:
                self.users = pickle.load(file)

    def get_users(self):
        try:
            with open(USERS_FILE_PATH, 'rb') as file:
                self.users = pickle.load(file)
                return self.users
        except:
            return "No Users"

    def set_file(self):
        with open(USERS_FILE_PATH, 'wb') as file:
            pickle.dump(self.users, file)

    def is_exist(self, username, password, email=None):
        """

        :param username: The username to check.
        :param password: The password to validate.
        :return: True if credentials are valid, False otherwise.
        """
        self.get_users()
        with lock:
            # for multy client use, each is_exist should be the most current
            if username in self.users.keys() and self.users[username].is_same_password(password):
                if (email is None) or (email is not None and self.users[username].get_email() == email):
                    return True
        return False

    def is_username_exist(self, username):
        with lock:
            return username in self.users.keys()

    def update_info(self, username, new_user_obj):
        with lock:
            self.users[username] = new_user_obj
            self.set_file()

    def add_user(self, username, password, email):
        self.get_users()
        if not self.is_username_exist(username) and self.get_user_by_email(email) is None \
                and not self.is_exist(username, password, email):
            # the User obj does the encryption MD5, salt, pepper..
            new_user = User(username, password, email)
            self.update_info(username, new_user)
            return True
        return False

    def get_user_by_email(self, email):
        for user in self.users.values():
            if user.get_email() == email:
                return user
        return None

    def get_user_by_username(self, username):
        for user in self.users.keys():
            if user == username:
                return self.users[username]
        return None


# CLASS PROTO: for sending and receiving messages

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
        self.dh_private_key = None
        self.dh_public_key = None
        self.shared_key = None
        self.parameters = None
        self.has_shared_key = False
        self.choosed_DH = False
        self.choosed_RSA = False
        self.lock = threading.Lock()
        self.logger = CustomLogger(f"PROTO for: {self.who_get}", logging_level)
        self.Print = self.logger.Print
        self.logging_level = logging_level

        self.name = ""

    def connect(self, ip, port):
        self.sock.connect((ip, port))

    # def send_first_proto_message(self, proto_name):
    #     msg = f"AVAIL|{proto_name}"
    #     self.send_one_message(msg.encode(), encryption=False)

    # def create_DH_keys(self):
    #     if self.parameters is None:
    #         self.parameters = dh.generate_parameters(generator=2, key_size=2048)
    #     self.dh_private_key = self.parameters.generate_private_key()
    #     self.dh_public_key = self.dh_private_key.public_key()
    #     self.choosed_DH = True

    # def get_public_key_dh(self):
    #     self.choosed_DH = True
    #     return self.dh_public_key.public_bytes(
    #         encoding=serialization.Encoding.PEM,
    #         format=serialization.PublicFormat.SubjectPublicKeyInfo
    #     )

    # def get_shared_key_dh(self):
    #     self.choosed_DH = True
    #     return self.shared_key

    # def get_dh_parameters(self):
    #     self.choosed_DH = True
    #     return self.parameters.parameter_bytes(
    #         encoding=serialization.Encoding.PEM,
    #         format=serialization.ParameterFormat.PKCS3
    #     )

    # def create_shared_key_dh(self, other_public_key_data):
    #     self.choosed_DH = True
    #     other_public_key = load_pem_public_key(other_public_key_data)
    #     self.shared_key = self.dh_private_key.exchange(other_public_key)
    #     self.has_shared_key = True

    # def set_parameters_dh(self, bin_data):
    #     self.choosed_DH = True

    #     self.parameters = load_pem_parameters(bin_data)
    #     self.create_DH_keys()

    # def create_RSA_keys(self):
    #     self.choosed_RSA = True
    #     self.RSA_private_key = rsa.generate_private_key(
    #         public_exponent=65537,
    #         key_size=2048
    #     )

    #     self.RSA_public_key = self.RSA_private_key.public_key()

    # def get_public_key_RSA(self):
    #     self.choosed_RSA = True

    #     pem_public = self.RSA_public_key.public_bytes(
    #         encoding=serialization.Encoding.PEM,
    #         format=serialization.PublicFormat.SubjectPublicKeyInfo
    #     )
    #     return pem_public

    # def set_RSA_public_key(self, bin_data):  # bin data in the pem_public in bytes
    #     self.choosed_RSA = True

    #     self.RSA_public_key = serialization.load_pem_public_key(bin_data)

    # def encrypt_AES_key_by_RSA_public_key(self):
    #     self.choosed_RSA = True

    #     self.AES_key = self.generate_AES_key()
    #     encrypted_key = self.RSA_public_key.encrypt(
    #         self.AES_key,
    #         padding.OAEP(
    #             mgf=padding.MGF1(algorithm=hashes.SHA256()),
    #             algorithm=hashes.SHA256(),
    #             label=None
    #         )
    #     )
    #     return encrypted_key

    # def get_encrypted_AES_key(self, data: bytes):  #data = AES encrypted by RSA public key
    #     self.choosed_RSA = True

    #     decrypted_data = self.RSA_private_key.decrypt(
    #         data,
    #         padding.OAEP(
    #             mgf=padding.MGF1(algorithm=hashes.SHA256()),
    #             algorithm=hashes.SHA256(),
    #             label=None
    #         )
    #     )
    #     self.AES_key = decrypted_data

    # def get_AES_key(self):
    #     return self.AES_key

    # # Function to encrypt data using AES CBC mode
    # def AES_encrypt(self, plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    #     # Pad the plaintext to block size
    #     padder = PADDING.PKCS7(AES.block_size).padder()
    #     padded_plaintext = padder.update(plaintext) + padder.finalize()

    #     # Create cipher and encrypt
    #     cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    #     encryptor = cipher.encryptor()
    #     ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
    #     return ciphertext

    # # Function to decrypt data using AES CBC mode
    # def AES_decrypt(self, ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    #     # Create cipher and decrypt
    #     cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    #     decryptor = cipher.decryptor()
    #     padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    #     # Unpad the plaintext
    #     unpadder = PADDING.PKCS7(AES.block_size).unpadder()
    #     plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    #     return plaintext

    def send_one_message(self, data: bytes, encryption=True):
        if encryption and self.choosed_DH:
            new_iv = self.generate_iv()
            shared_key_in_sha256 = hashlib.sha256(self.shared_key).digest()
            message = new_iv + self.AES_encrypt(data, shared_key_in_sha256, new_iv)
        elif encryption and self.choosed_RSA:
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


class Func:
    def __init__(self, subject=None, color=None, moves=None, opponent=None, who_start=None, num1=0, num2=0, info="",
                 pt=None, turn="", from_pt=-1, to_pt=-1, points=None, game_over=None):
        self.opponent = opponent
        self.color = color
        self.moves = moves
        self.subject = subject
        self.who_start = who_start
        self.num1 = num1
        self.num2 = num2
        self.info = info
        self.pt = pt  # point on the board from 1-24
        self.turn = turn
        self.from_pt = from_pt
        self.to_pt = to_pt
        self.points = points # reach to points
        self.game_over = game_over

    def to_str(self):
        msg = []
        if self.subject:
            msg.append(f"subject={self.subject}")
        if self.color:
            msg.append(f"color={self.color}")
        if self.moves:
            msg.append(f"moves={self.moves}")
        if self.who_start:
            msg.append(f"who_start={self.who_start}")
        if self.opponent:
            msg.append(f"opponent={self.opponent}")
        if self.num1:
            msg.append(f"num1={self.num1}")
        if self.num2:
            msg.append(f"num2={self.num2}")
        if self.info:
            msg.append(f"info={self.info}")
        if self.pt is not None:  # 0 will be false, so check
            msg.append(f"pt={self.pt}")
        if self.turn:
            msg.append(f"turn={self.turn}")
        if self.from_pt >= 0:
            msg.append(f"from_pt={self.from_pt}")
        if self.to_pt >= 0:
            msg.append(f"to_pt={self.to_pt}")
        if self.points:
            msg.append(f"points={self.points}")
        if self.game_over:
            msg.append(f"game_over={self.game_over}")
        return "|".join(msg)

    @classmethod
    def from_str(cls, message):
        parts = message.split("|")
        kwargs = {}
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                kwargs[k] = v
        return cls(**kwargs)  # **kwargs unpacks the dict into params for the constructor


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
