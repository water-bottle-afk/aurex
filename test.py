class Communication:
    def log(self, dirct, data):
        
        if dirct == 'recv':
            self.Print("got <<<<< " + data)
        else:
            self.Print("sent >>>>> " + data)

    def __init__(self, sock, name=""):
        self.sock = sock
        self.shared_key = None
        self.parameters = None
        self.lock = threading.Lock()
        self.Print = print
        self.name = name
        self.AES_key = None
        

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


    def send_one_message(self, data: dict, encryption=True):
        data_json = json.dumps(data, sort_keys=True).encode()
        
        if encryption:
            new_iv = self.generate_iv()
            message = new_iv + self.AES_encrypt(data_json, self.AES_key, new_iv)
        else:
            message = data_json

        self.sock.send(struct.pack('!H', len(message)) + message)
        self.log('send', data_json.decode())


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
            self.log('recv', data.decode())
            return json.loads(data.decode())
        except Exception as e:
            print(f"Error decoding JSON: {e}")
            return None

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
        self.Print(f"Closes {self.name} socket!")
        self.sock.close()

class RSA_Client:
    def __init__(self, ip, port, name="RSA_Client"):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.communication = Communication(sock=self.sock, name=name)
        
    def start(self):
        self.sock.connect((self.ip, self.port))
        self.contact_with_RSA()
        # Now you can use proto to send/receive encrypted messages with the server


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
        print(f"Closes Client socket!", 10)
        self.sock.close()

class RSA_Server:
    def __init__(self, ip, port, dir_for_keys=None, Gateway=False,name="RSA_Server", role=""):
        self.ip = ip
        self.port = port
        self.dir_for_keys = dir_for_keys
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.ip, self.port))
        self.sock.listen(5 if not Gateway else 10)
        self.role = role

    def start(self):
        if self.role == "Gateway" or self.role == "Blockchain Node":
            while True:
                self.client_sock, addr = self.sock.accept()
                t = threading.Thread(target=self.handle_client, daemon=True, args=(self.client_sock,))
                t.start()
        

    def handle_client(self, client_socket):
        communication = Communication(client_socket, name="Server")
        self.contact_with_RSA(communication)
        
        if self.inside_server:
            return
            
        while True:
            msg = communication.recv_one_message()
            if msg is None:
                break
            # Handle the received message (e.g., process transactions, etc.)
            communication.send_one_message({"type": "ACK", "content": "Message received"})

        communication.close()
        
    def contact_with_RSA(self, communication):
        answer =  communication.recv_one_message(False)
        if answer is None:
            print("recved none from client, closing connection")
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

