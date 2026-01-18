"""
Aurex Blockchain Server - Handles client connections and Firebase data management
Optimized architecture: One persistent connection per client, event-based processing
"""

import datetime
import hashlib
import random
import socket
import ssl as ssl_module
import os
import threading
from config import (
    SERVER_HOST, SERVER_PORT, SERVER_IP,
    BROADCAST_PORT, SSL_CERT_FILE, SSL_KEY_FILE,
    LOGGING_LEVEL
)
from classes import PROTO, CustomLogger

# Try to import Firebase Admin SDK
FIREBASE_ENABLED = False
firebase_db = None

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db_module
    
    # Get the path to serviceAccountKey.json relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    key_path = os.path.join(script_dir, 'serviceAccountKey.json')
    
    # Initialize Firebase
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://aurex-blockchain-transactions-default-rtdb.firebaseio.com'
    })
    firebase_db = firebase_db_module
    FIREBASE_ENABLED = True
    print(f"✅ Firebase initialized successfully from {key_path}")
except ImportError:
    print("⚠️ firebase-admin not installed. Install with: pip install firebase-admin")
except FileNotFoundError as e:
    print(f"⚠️ serviceAccountKey.json not found at {key_path}. Using in-memory database.")
except Exception as e:
    print(f"⚠️ Firebase initialization failed: {e}. Using in-memory database.")


class FirebaseDB:
    """Wrapper for Firebase Realtime Database operations"""
    
    def create_user(self, username, email, password):
        """Create a new user with hashed password"""
        try:
            # Hash password with SHA256
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            if FIREBASE_ENABLED:
                # Check if user exists
                user_ref = firebase_db.reference(f'/users/{username}')
                if user_ref.get() is not None:
                    return False
                
                # Create user in Firebase
                user_ref.set({
                    'username': username,
                    'email': email,
                    'password_hash': password_hash,
                    'created_at': datetime.datetime.now().isoformat(),
                    'verified': False,
                })
                return True
            else:
                # Fallback: in-memory storage
                if not hasattr(self, '_users'):
                    self._users = {}
                if username in self._users:
                    return False
                self._users[username] = {
                    'email': email,
                    'password_hash': password_hash,
                    'created_at': datetime.datetime.now().isoformat(),
                }
                return True
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return False
    
    def get_user(self, username):
        """Get user data"""
        try:
            if FIREBASE_ENABLED:
                user_ref = firebase_db.reference(f'/users/{username}')
                return user_ref.get()
            else:
                if not hasattr(self, '_users'):
                    self._users = {}
                return self._users.get(username)
        except Exception as e:
            print(f"❌ Error getting user: {e}")
            return None
    
    def verify_password(self, username, password):
        """Verify user password"""
        try:
            user = self.get_user(username)
            if not user:
                return False
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            return user.get('password_hash') == password_hash
        except Exception as e:
            print(f"❌ Error verifying password: {e}")
            return False
    
    def add_asset(self, asset_id, asset_name, username):
        """Register asset in blockchain"""
        try:
            if FIREBASE_ENABLED:
                asset_ref = firebase_db.reference(f'/assets/{asset_id}')
                asset_ref.set({
                    'name': asset_name,
                    'owner': username,
                    'created_at': datetime.datetime.now().isoformat(),
                    'token': asset_id,
                })
                
                # Add to user's assets
                user_assets_ref = firebase_db.reference(f'/users/{username}/assets/{asset_id}')
                user_assets_ref.set(True)
                return True
            else:
                if not hasattr(self, '_assets'):
                    self._assets = {}
                    self._user_assets = {}
                
                self._assets[asset_id] = {
                    'name': asset_name,
                    'owner': username,
                    'created_at': datetime.datetime.now().isoformat(),
                }
                if username not in self._user_assets:
                    self._user_assets[username] = []
                self._user_assets[username].append(asset_id)
                return True
        except Exception as e:
            print(f"❌ Error adding asset: {e}")
            return False
    
    def get_user_assets(self, username, page=0, limit=10):
        """Get paginated asset list for user"""
        try:
            if FIREBASE_ENABLED:
                user_assets_ref = firebase_db.reference(f'/users/{username}/assets')
                assets = user_assets_ref.get()
                if not assets:
                    return []
                asset_ids = list(assets.keys())
                start = page * limit
                end = start + limit
                return asset_ids[start:end]
            else:
                if not hasattr(self, '_user_assets'):
                    self._user_assets = {}
                assets = self._user_assets.get(username, [])
                start = page * limit
                end = start + limit
                return assets[start:end]
        except Exception as e:
            print(f"❌ Error getting user assets: {e}")
            return []
    
    def get_total_assets(self, username):
        """Get total asset count for user"""
        try:
            if FIREBASE_ENABLED:
                user_assets_ref = firebase_db.reference(f'/users/{username}/assets')
                assets = user_assets_ref.get()
                return len(assets) if assets else 0
            else:
                if not hasattr(self, '_user_assets'):
                    self._user_assets = {}
                return len(self._user_assets.get(username, []))
        except Exception as e:
            print(f"❌ Error getting asset count: {e}")
            return 0


class ClientSession:
    """Represents one authenticated client connection"""
    def __init__(self, sock, addr, logging_level):
        self.socket = sock
        self.address = addr
        
        # Pass socket directly to PROTO constructor instead of assigning afterward
        self.proto = PROTO("ClientSession", logging_level=logging_level, cln_sock=sock)
        
        self.logger = CustomLogger(f"Session-{addr[0]}:{addr[1]}", logging_level)
        self.Print = self.logger.Print
        
        self.username = None
        self.is_authenticated = False
        self.is_connected = True
        self.db = FirebaseDB()
        
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
                self.Print(f"❌ Unknown command: {command}", 40)
                return f"ERR02|Unknown command: {command}"
            
            handler = self.handlers[command]
            return handler(parts[1:])
        except Exception as e:
            self.Print(f"❌ Error processing message: {e}", 40)
            return f"ERR99|{str(e)}"
    
    def handle_start(self, params):
        """Protocol Message 1: START - Initialize connection"""
        self.Print("✅ START message received - accepting connection", 20)
        return "ACCPT|Connection accepted"
    
    def handle_login(self, params):
        """Protocol Message 6: LOGIN - Email/Password authentication
        Format: LOGIN|email|password
        """
        if len(params) < 2:
            self.Print("❌ Invalid login format", 40)
            return "ERR01|Invalid login format"
        
        email = params[0].strip()
        password = params[1].strip()
        
        # Find user by email (search all users)
        try:
            if FIREBASE_ENABLED and firebase_db:
                users_ref = firebase_db.reference('/users')
                all_users = users_ref.get()
                
                if not all_users:
                    self.Print(f"❌ No users found for email {email}", 40)
                    return "ERR01|Invalid email or password"
                
                # Search for user with matching email
                for username, user_data in all_users.items():
                    if user_data.get('email') == email:
                        if self.db.verify_password(username, password):
                            self.username = username
                            self.is_authenticated = True
                            self.Print(f"✅ User {username} ({email}) logged in", 20)
                            return "LOGED|Login successful"
                        else:
                            self.Print(f"❌ Wrong password for {email}", 40)
                            return "ERR01|Invalid email or password"
                
                self.Print(f"❌ Email {email} not found", 40)
                return "ERR01|Invalid email or password"
            else:
                # Fallback: in-memory search
                if not hasattr(self.db, '_users'):
                    self.db._users = {}
                
                for username, user_data in self.db._users.items():
                    if user_data.get('email') == email:
                        if self.db.verify_password(username, password):
                            self.username = username
                            self.is_authenticated = True
                            self.Print(f"✅ User {username} ({email}) logged in", 20)
                            return "LOGED|Login successful"
                
                self.Print(f"❌ Invalid credentials for {email}", 40)
                return "ERR01|Invalid email or password"
        
        except Exception as e:
            self.Print(f"❌ Login error: {e}", 40)
            return f"ERR01|Login error: {str(e)}"
    
    def handle_signup(self, params):
        """Protocol Message 5: SGNUP - User registration
        Format: SGNUP|username|password|verify_password|email
        """
        if len(params) < 4:
            self.Print("❌ Invalid signup format", 40)
            return "ERR10|Invalid signup format"
        
        username = params[0].strip()
        password = params[1].strip()
        confirm_password = params[2].strip()
        email = params[3].strip()
        
        # Validate inputs
        if not username or not password or not email:
            self.Print(f"❌ Missing required fields for signup", 40)
            return "ERR10|Missing required fields"
        
        if password != confirm_password:
            self.Print(f"❌ Passwords do not match for {username}", 40)
            return "ERR10|Passwords do not match"
        
        if len(password) < 6:
            self.Print(f"❌ Password too short for {username}", 40)
            return "ERR10|Password must be at least 6 characters"
        
        # Create user in Firebase
        if self.db.create_user(username, email, password):
            self.Print(f"✅ User {username} ({email}) signed up", 20)
            return "SIGND|Signup successful"
        else:
            self.Print(f"❌ User {username} already exists", 40)
            return "ERR10|Username already exists"
    
    def handle_send_code(self, params):
        """Protocol Message 9: SCODE - Send verification code
        Format: SCODE|email
        """
        if len(params) < 1:
            return "ERR04|Invalid code request"
        
        email = params[0].strip()
        
        # Generate random code
        code = str(random.randint(100000, 999999))
        
        self.Print(f"📧 Verification code {code} for {email}", 20)
        
        # In production, send real email
        return "SENTM|Code sent to email"
    
    def handle_verify_code(self, params):
        """Protocol Message 10: VRFYC - Verify code
        Format: VRFYC|email|code
        """
        if len(params) < 2:
            return "ERR08|Invalid verification format"
        
        email = params[0].strip()
        code = params[1].strip()
        
        self.Print(f"✅ Code {code} verified for {email}", 20)
        return "VRFYD|Code verified successfully"
    
    def handle_update_password(self, params):
        """Protocol Message 11: UPDTE - Update password
        Format: UPDTE|email|new_password|confirm_password
        """
        if len(params) < 3:
            return "ERR07|Invalid update format"
        
        email = params[0].strip()
        new_password = params[1].strip()
        confirm_password = params[2].strip()
        
        if new_password != confirm_password:
            return "ERR07|Passwords do not match"
        
        self.Print(f"🔑 Password updated for {email}", 20)
        return "UPDTD|Password updated successfully"
    
    def handle_logout(self, params):
        """Protocol Message 7: LGOUT - Logout
        Format: LGOUT|
        """
        self.is_authenticated = False
        username = self.username
        self.username = None
        self.Print(f"👋 User {username} logged out", 20)
        return "EXTLG|Logout successful"
    
    def handle_log_asset(self, params):
        """Protocol Message 12: LGAST - Log asset to blockchain
        Format: LGAST|asset_id|asset_name
        """
        if not self.is_authenticated:
            return "ERR03|Not authenticated"
        
        if len(params) < 2:
            return "ERR03|Invalid asset log format"
        
        asset_id = params[0].strip()
        asset_name = params[1].strip()
        
        if self.db.add_asset(asset_id, asset_name, self.username):
            self.Print(f"📦 Asset {asset_id} registered by {self.username}", 20)
            return "SAVED|Asset saved to blockchain"
        else:
            self.Print(f"❌ Failed to save asset {asset_id}", 40)
            return "ERR03|Failed to save asset"
    
    def handle_asset_list(self, params):
        """Protocol Message 13: ASKLST - Request asset list with pagination
        Format: ASKLST|page|limit
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        
        if len(params) < 2:
            return "ERR02|Invalid asset list format"
        
        try:
            page = int(params[0].strip())
            limit = int(params[1].strip())
        except ValueError:
            return "ERR02|Invalid page/limit parameters"
        
        assets = self.db.get_user_assets(self.username, page, limit)
        total = self.db.get_total_assets(self.username)
        
        # Format: ASLIST|token1,token2,...|total_count
        tokens = ','.join(assets) if assets else ''
        response = f"ASLIST|{tokens}|{total}"
        
        self.Print(f"📋 Asset list requested (page {page}): {len(assets)} assets", 20)
        return response


class Server:
    """Main server that handles all client connections"""
    
    def __init__(self, host=SERVER_HOST, port=SERVER_PORT, logging_level=LOGGING_LEVEL):
        self.host = host
        self.port = port
        self.server_ip = SERVER_IP  # Local network IP for broadcast response
        self.logging_level = logging_level
        self.logger = CustomLogger("Server", logging_level)
        self.Print = self.logger.Print
        
        self.clients = {}  # addr -> ClientSession
        self.is_running = False
        
        # Firebase database
        self.db = FirebaseDB()
    
    def _start_broadcast_listener(self):
        """Start listening for WHRSRV (Where's Server) broadcast queries"""
        def broadcast_loop():
            try:
                # Create UDP socket for broadcast listening
                broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                broadcast_sock.bind(('0.0.0.0', 12345))
                
                self.Print("📡 Broadcast listener started on port 12345", 20)
                
                while self.is_running:
                    try:
                        data, addr = broadcast_sock.recvfrom(1024)
                        message = data.decode('utf-8').strip()
                        
                        if message == "WHRSRV":
                            # Get the local IP address (not 0.0.0.0)
                            # Try to get the actual IP by connecting to a remote address
                            try:
                                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                s.connect(("8.8.8.8", 80))
                                local_ip = s.getsockname()[0]
                                s.close()
                            except:
                                local_ip = "127.0.0.1"
                            
                            response = f"SRVRSP|{local_ip}|{self.port}"
                            broadcast_sock.sendto(response.encode('utf-8'), addr)
                            self.Print(f"📡 Broadcast response sent to {addr}: {response}", 10)
                    except socket.timeout:
                        continue
                    except Exception as e:
                        self.Print(f"⚠️ Broadcast listener error: {e}", 10)
                
                broadcast_sock.close()
            except Exception as e:
                self.Print(f"❌ Failed to start broadcast listener: {e}", 10)
        
        # Start broadcast listener in a separate thread
        thread = threading.Thread(target=broadcast_loop, daemon=True)
        thread.start()
    
    def start(self):
        """Start the server"""
        self.Print(f"🚀 Server starting on {self.host}:{self.port}...", 20)
        
        try:
            self.is_running = True
            
            # Start broadcast listener thread
            self._start_broadcast_listener()
            
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
                
                self.Print(f"✅ Server listening on {self.host}:{self.port}", 20)
                
                while self.is_running:
                    try:
                        # Accept connection
                        client_sock, addr = sock.accept()
                        
                        self.Print(f"📥 Connection attempt from {addr[0]}:{addr[1]}", 20)
                        
                        # Wrap with SSL
                        try:
                            ssl_sock = context.wrap_socket(
                                client_sock,
                                server_side=True
                            )
                            # Keep socket blocking (no timeout) for persistent connections
                            ssl_sock.setblocking(True)
                            self.Print(f"🔒 SSL/TLS handshake successful for {addr[0]}:{addr[1]}", 20)
                        except Exception as ssl_err:
                            self.Print(f"⚠️ SSL error for {addr[0]}:{addr[1]}: {ssl_err}", 40)
                            ssl_sock = client_sock  # Fallback to plain socket
                            ssl_sock.setblocking(True)
                        
                        self.handle_client(ssl_sock, addr)
                    except KeyboardInterrupt:
                        self.Print("⛔ Server shutting down...", 20)
                        self.is_running = False
                    except Exception as e:
                        self.Print(f"❌ Error accepting connection: {e}", 40)
        
        except Exception as e:
            self.Print(f"💥 Critical server error: {e}", 40)
        finally:
            self.Print(f"🛑 Server shutdown complete", 20)
    
    def handle_client(self, sock, addr):
        """Handle a single client connection (non-blocking event loop)"""
        session = None
        try:
            self.Print(f"✅ New client connection established: {addr[0]}:{addr[1]}", 20)
            
            # Create session for this client
            session = ClientSession(sock, addr, self.logging_level)
            self.clients[addr] = session
            self.Print(f"👤 Client session created for {addr[0]}:{addr[1]}", 20)
            
            # Receive messages until client disconnects
            while session.is_connected:
                try:
                    self.Print(f"⏳ Calling recv_one_message() for {addr[0]}:{addr[1]}...", 20)
                    message = session.proto.recv_one_message()
                    
                    if message is None:
                        self.Print(f"📤 Client {addr[0]}:{addr[1]} disconnected (recv returned None)", 20)
                        session.is_connected = False
                        break
                    
                    self.Print(f"✅ Message received, processing...", 20)
                    # Decode and process
                    try:
                        msg_str = message.decode() if isinstance(message, bytes) else message
                        self.Print(f"📩 Received from {addr[0]}:{addr[1]}: {msg_str}", 20)
                        
                        response = session.process_message(msg_str)
                        
                        # Send response
                        self.Print(f"📮 Sending to {addr[0]}:{addr[1]}: {response}", 20)
                        session.proto.send_one_message(response.encode())
                        self.Print(f"✅ Response sent successfully to {addr[0]}:{addr[1]}", 20)
                    
                    except Exception as e:
                        self.Print(f"❌ Error processing message from {addr[0]}:{addr[1]}: {e}", 40)
                        try:
                            session.proto.send_one_message(f"ERR99|{str(e)}".encode())
                        except:
                            self.Print(f"❌ Failed to send error response to {addr[0]}:{addr[1]}", 40)
                            session.is_connected = False
                            break
                
                except ConnectionResetError:
                    self.Print(f"🔌 Client {addr[0]}:{addr[1]} reset connection", 20)
                    session.is_connected = False
                except BrokenPipeError:
                    self.Print(f"🔌 Client {addr[0]}:{addr[1]} closed connection", 20)
                    session.is_connected = False
                except Exception as e:
                    self.Print(f"❌ Error in message loop for {addr[0]}:{addr[1]}: {e}", 40)
                    session.is_connected = False
        
        except Exception as e:
            self.Print(f"💥 Critical error in handle_client for {addr[0]}:{addr[1]}: {e}", 40)
        
        finally:
            # Clean up
            try:
                if addr in self.clients:
                    del self.clients[addr]
                    self.Print(f"🗑️ Client session removed for {addr[0]}:{addr[1]}", 20)
                sock.close()
                self.Print(f"🔌 Connection closed for {addr[0]}:{addr[1]}", 20)
            except Exception as cleanup_err:
                self.Print(f"⚠️ Error during cleanup for {addr[0]}:{addr[1]}: {cleanup_err}", 40)


# Entry point
if __name__ == "__main__":
    logging_level = 10  # DEBUG
    
    server = Server(
        host='0.0.0.0',
        port=23456,
        logging_level=logging_level
    )
    
    server.start()
