"""
Node Key Management - Each node has its own public/private key pair
Used for signing blocks and verifying authenticity
"""

import os
import json
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend


class NodeKeyManager:
    """Manages public/private keys for a node"""
    
    def __init__(self, node_id, key_dir='keys'):
        """Initialize key manager for a node"""
        self.node_id = node_id
        self.key_dir = key_dir
        self.private_key = None
        self.public_key = None
        
        # Create keys directory
        os.makedirs(key_dir, exist_ok=True)
        
        # Load or generate keys
        self._load_or_generate_keys()
    
    def _load_or_generate_keys(self):
        """Load existing keys or generate new ones"""
        private_key_path = os.path.join(self.key_dir, f"{self.node_id}_private.pem")
        public_key_path = os.path.join(self.key_dir, f"{self.node_id}_public.pem")
        
        if os.path.exists(private_key_path) and os.path.exists(public_key_path):
            # Load existing keys
            with open(private_key_path, 'rb') as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
            
            with open(public_key_path, 'rb') as f:
                self.public_key = serialization.load_pem_public_key(
                    f.read(),
                    backend=default_backend()
                )
            
            print(f" Loaded existing keys for {self.node_id}")
        else:
            # Generate new keys
            self.private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            self.public_key = self.private_key.public_key()
            
            # Save keys
            with open(private_key_path, 'wb') as f:
                f.write(self.private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            with open(public_key_path, 'wb') as f:
                f.write(self.public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))
            
            print(f" Generated new keys for {self.node_id}")
    
    def sign_data(self, data):
        """Sign data with private key"""
        if isinstance(data, str):
            data = data.encode()
        
        signature = self.private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        return signature.hex()
    
    def get_public_key_pem(self):
        """Get public key in PEM format as string"""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
    
    @staticmethod
    def verify_signature(public_key_pem, data, signature_hex):
        """Verify a signature using public key"""
        try:
            if isinstance(data, str):
                data = data.encode()
            
            signature = bytes.fromhex(signature_hex)
            
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode(),
                backend=default_backend()
            )
            
            public_key.verify(
                signature,
                data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
        except:
            return False
