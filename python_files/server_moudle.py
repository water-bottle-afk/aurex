"""
Aurex Blockchain Server - Handles client connections and Firebase data management
Optimized architecture: One persistent connection per client, event-based processing
"""

import datetime
import smtplib
import ssl
from email.message import EmailMessage
import random
import socket
import ssl as ssl_module
from classes import PROTO, CustomLogger

# Mock Firebase for now (replace with actual Firebase SDK)
class FirebaseDB:
    """Simple in-memory database simulating Firebase"""
    def __init__(self):
        self.users = {}  # username -> user_data
        self.assets = {}  # asset_id -> asset_data
        self.user_assets = {}  # username -> [asset_ids]
    
    def create_user(self, username, email, password_hash):
        if username in self.users:
            return False
        self.users[username] = {
            'email': email,
            'password_hash': password_hash,
            'created_at': datetime.datetime.now(),
        }
        self.user_assets[username] = []
        return True
    
    def get_user(self, username):
        return self.users.get(username)
    
    def verify_password(self, username, password_hash):
        user = self.users.get(username)
        if user and user['password_hash'] == password_hash:
            return True
        return False
    
    def add_asset(self, asset_id, asset_name, username):
        """Register asset in blockchain"""
        self.assets[asset_id] = {
            'name': asset_name,
            'owner': username,
            'created_at': datetime.datetime.now(),
            'token': asset_id,
        }
        if username in self.user_assets:
            self.user_assets[username].append(asset_id)
        return True
    
    def get_user_assets(self, username, page=0, limit=10):
        """Get paginated asset list for user"""
        if username not in self.user_assets:
            return []
        
        assets = self.user_assets[username]
        start = page * limit
        end = start + limit
        return assets[start:end]
    
    def get_total_assets(self, username):
        """Get total asset count for user"""
        return len(self.user_assets.get(username, []))


class ClientSession:
    """Represents one authenticated client connection"""
    def __init__(self, sock, addr, logging_level):
        self.socket = sock
        self.address = addr
        self.proto = PROTO("ClientSession", logging_level=logging_level)
        self.proto.socket = sock  # Use existing connection
        
        self.logger = CustomLogger(f"Session-{addr[0]}:{addr[1]}", logging_level)
        self.Print = self.logger.Print
        
        self.username = None
        self.is_authenticated = False
        self.is_connected = True
        
        # Message handlers
        self.handlers = {
            "START": self.handle_start,
            "LOGIN": self.handle_login,
            "SGNUP": self.handle_signup,
            "SCODE": self.handle_send_code,
            "VRFYC": self.handle_verify_code,
            "UPDTE": self.handle_update_password,
            "LGOUT": self.handle_logout,
            "LGAST": self.handle_log_asset,
            "ASKLST": self.handle_asset_list,
        }
    
    def process_message(self, message):
        """Parse and handle incoming message"""
        try:
            parts = message.split('|')
            command = parts[0].strip()
            
            if command not in self.handlers:
                return f"ERR02|Unknown command: {command}"
            
            handler = self.handlers[command]
            return handler(parts[1:])
        except Exception as e:
            self.Print(f"Error processing message: {e}", 40)
            return f"ERR99|{str(e)}"
    
    def handle_start(self, params):
        """Protocol Message 1: START - Initialize connection"""
        self.Print("START message received - accepting connection", 20)
        return "ACCPT|Connection accepted"
    
    def handle_login(self, params):
        """Protocol Message 6: LOGIN"""
        if len(params) < 2:
            return "ERR01|Invalid login format"
        
        username = params[0].strip()
        password = params[1].strip()
        
        # In production, hash password and verify
        if username in FirebaseDB().users:
            self.username = username
            self.is_authenticated = True
            self.Print(f"User {username} logged in", 20)
            return "LOGED|Login successful"
        else:
            return "ERR01|Invalid credentials"
    
    def handle_signup(self, params):
        """Protocol Message 5: SGNUP"""
        if len(params) < 4:
            return "ERR10|Invalid signup format"
        
        username = params[0].strip()
        password = params[1].strip()
        confirm_password = params[2].strip()
        email = params[3].strip()
        
        if password != confirm_password:
            return "ERR10|Passwords do not match"
        
        # In production, hash password and use real Firebase
        db = FirebaseDB()
        if db.create_user(username, email, password):
            self.Print(f"User {username} signed up", 20)
            return "SIGND|Signup successful"
        else:
            return "ERR10|Username already exists"
    
    def handle_send_code(self, params):
        """Protocol Message 9: SCODE - Send verification code"""
        if len(params) < 1:
            return "ERR04|Invalid code request"
        
        email = params[0].strip()
        
        # Generate random code
        code = str(random.randint(100000, 999999))
        
        # In production, send real email via SMTP
        self.Print(f"Verification code {code} for {email}", 20)
        
        return "SENTM|Code sent to email"
    
    def handle_verify_code(self, params):
        """Protocol Message 10: VRFYC"""
        if len(params) < 2:
            return "ERR08|Invalid verification format"
        
        email = params[0].strip()
        code = params[1].strip()
        
        # In production, verify against stored code
        self.Print(f"Code {code} verified for {email}", 20)
        
        return "VRFYD|Code verified successfully"
    
    def handle_update_password(self, params):
        """Protocol Message 11: UPDTE"""
        if len(params) < 3:
            return "ERR07|Invalid update format"
        
        email = params[0].strip()
        new_password = params[1].strip()
        confirm_password = params[2].strip()
        
        if new_password != confirm_password:
            return "ERR07|Passwords do not match"
        
        self.Print(f"Password updated for {email}", 20)
        return "UPDTD|Password updated successfully"
    
    def handle_logout(self, params):
        """Protocol Message 7: LGOUT"""
        self.is_authenticated = False
        self.username = None
        self.Print("User logged out", 20)
        return "EXTLG|Logout successful"
    
    def handle_log_asset(self, params):
        """Protocol Message 12: LGAST - Log asset to blockchain"""
        if not self.is_authenticated:
            return "ERR03|Not authenticated"
        
        if len(params) < 2:
            return "ERR03|Invalid asset log format"
        
        asset_id = params[0].strip()
        asset_name = params[1].strip()
        
        db = FirebaseDB()
        if db.add_asset(asset_id, asset_name, self.username):
            self.Print(f"Asset {asset_id} registered by {self.username}", 20)
            return "SAVED|Asset saved to blockchain"
        else:
            return "ERR03|Failed to save asset"
    
    def handle_asset_list(self, params):
        """Protocol Message 13: ASKLST - Request asset list with pagination"""
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        
        if len(params) < 2:
            return "ERR02|Invalid asset list format"
        
        try:
            page = int(params[0].strip())
            limit = int(params[1].strip())
        except ValueError:
            return "ERR02|Invalid page/limit parameters"
        
        db = FirebaseDB()
        assets = db.get_user_assets(self.username, page, limit)
        total = db.get_total_assets(self.username)
        
        # Format: ASLIST|token1,token2,...|total_count
        tokens = ','.join(assets)
        response = f"ASLIST|{tokens}|{total}"
        
        self.Print(f"Asset list requested (page {page}): {tokens}", 20)
        return response


class Server:
    """Main server that handles all client connections"""
    
    def __init__(self, host='0.0.0.0', port=23456, logging_level=10):
        self.host = host
        self.port = port
        self.logging_level = logging_level
        self.logger = CustomLogger("Server", logging_level)
        self.Print = self.logger.Print
        
        self.clients = {}  # addr -> ClientSession
        self.is_running = False
        
        # Firebase database
        self.db = FirebaseDB()
    
    def start(self):
        """Start the server"""
        try:
            self.is_running = True
            
            # Create SSL context
            context = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(
                certfile='cert.pem',
                keyfile='key.pem'
            )
            
            # Create socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((self.host, self.port))
                sock.listen(5)
                
                self.Print(f"Server listening on {self.host}:{self.port}", 20)
                
                while self.is_running:
                    try:
                        # Accept connection
                        client_sock, addr = sock.accept()
                        
                        # Wrap with SSL
                        try:
                            ssl_sock = context.wrap_socket(
                                client_sock,
                                server_side=True
                            )
                        except:
                            ssl_sock = client_sock  # Fallback to plain socket
                        
                        self.handle_client(ssl_sock, addr)
                    except KeyboardInterrupt:
                        self.Print("Server shutting down...", 20)
                        self.is_running = False
                    except Exception as e:
                        self.Print(f"Error accepting connection: {e}", 40)
        
        except Exception as e:
            self.Print(f"Server error: {e}", 40)
    
    def handle_client(self, sock, addr):
        """Handle a single client connection (non-blocking event loop)"""
        try:
            self.Print(f"New connection from {addr}", 20)
            
            # Create session for this client
            session = ClientSession(sock, addr, self.logging_level)
            self.clients[addr] = session
            
            # Receive messages until client disconnects
            while session.is_connected:
                try:
                    message = session.proto.recv_one_message()
                    
                    if message is None:
                        self.Print(f"Client {addr} disconnected", 20)
                        session.is_connected = False
                        break
                    
                    # Decode and process
                    try:
                        msg_str = message.decode() if isinstance(message, bytes) else message
                        response = session.process_message(msg_str)
                        
                        # Send response
                        session.proto.send_one_message(response.encode())
                    
                    except Exception as e:
                        self.Print(f"Error processing message from {addr}: {e}", 40)
                        session.proto.send_one_message(f"ERR99|{str(e)}".encode())
                
                except Exception as e:
                    self.Print(f"Error receiving from {addr}: {e}", 40)
                    session.is_connected = False
        
        finally:
            # Clean up
            if addr in self.clients:
                del self.clients[addr]
            sock.close()
            self.Print(f"Connection from {addr} closed", 20)


# Entry point
if __name__ == "__main__":
    logging_level = 10  # DEBUG
    
    server = Server(
        host='0.0.0.0',
        port=23456,
        logging_level=logging_level
    )
    
    server.start()
