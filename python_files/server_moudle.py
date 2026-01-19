"""
Aurex Blockchain Server - Handles client connections and Firebase data management
Optimized architecture: One persistent connection per client, event-based processing

PROTOCOL SPECIFICATION
======================
All client-server communication uses TLS on port 23456 with 2-byte length prefix.

Message Format: [2-byte length][protocol command]

Supported Commands:
  1. START - Connection initialization
     Send: START|Client_Flutter_App
     Recv: ACCPT|Connection accepted
  
  2. LOGIN - User authentication (by EMAIL)
     Send: LOGIN|email|password
     Recv: OK|username|email or ERR|error_message
  
  3. SIGNUP - User registration (Anonymous profile, username only)
     Send: SIGNUP|username|password|email
     Recv: OK or ERR|error_message
  
  4. SEND_CODE - Request password reset OTP code via email
     Send: SEND_CODE|email
     Recv: OK|code_sent or ERR|error_message
  
  5. VERIFY_CODE - Verify OTP code for password reset
     Send: VERIFY_CODE|email|otp_code
     Recv: OK|token or ERR|error_message
  
  6. UPDATE_PASSWORD - Change user password (after OTP verification)
     Send: UPDATE_PASSWORD|email|new_password
     Recv: OK or ERR|error_message
  
  7. LOGOUT - User logout
     Send: LOGOUT|username
     Recv: OK or ERR|error_message
  
  8. UPLOAD - Upload/register marketplace item (asset)
     Send: UPLOAD|asset_name|username|google_drive_url|file_type|cost
     Recv: OK|asset_id or ERR|error_message
  
  9. GET_ITEMS - Get all marketplace items
     Send: GET_ITEMS
     Recv: OK|item1|item2|... or ERR|error_message
  
  10. GET_ITEMS_PAGINATED - Lazy scrolling with timestamp cursor
      Send: GET_ITEMS_PAGINATED|limit[|timestamp]
      Recv: OK|item1|item2|... or ERR|error_message
  
  11. BUY - Purchase an asset from marketplace
      Send: BUY|asset_id|username|amount
      Recv: OK|transaction_id or ERR|error_message
  
  12. SEND - Send purchased asset to another user
      Send: SEND|asset_id|sender_username|receiver_username
      Recv: OK|transaction_id or ERR|error_message
  
  13. GET_PROFILE - Get user profile (anonymous - username only)
      Send: GET_PROFILE|username
      Recv: OK|username|email|created_at or ERR|error_message
"""

import datetime
import hashlib
import random
import socket
import ssl as ssl_module
import os
import threading
import time
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
        
        # Message handlers - Protocol Command Mapping
        # Client → Server protocol messages
        self.handlers = {
            # Connection & Auth
            "START": self.handle_start,                         # Connection initialization
            "LOGIN": self.handle_login,                         # User login by username
            "SIGNUP": self.handle_signup,                       # User registration (anonymous)
            "SEND_CODE": self.handle_send_code,                # Request OTP code for password reset
            "VERIFY_CODE": self.handle_verify_code,           # Verify OTP code
            "UPDATE_PASSWORD": self.handle_update_password,   # Change password
            "LOGOUT": self.handle_logout,                       # User logout
            # Marketplace Operations
            "UPLOAD": self.handle_log_asset,                    # Upload/list marketplace item
            "GET_ITEMS": self.handle_asset_list,               # Get all marketplace items
            "GET_ITEMS_PAGINATED": self.handle_get_items_paginated,  # Lazy scroll with cursor
            "BUY": self.handle_buy_asset,                       # Purchase an asset
            "SEND": self.handle_send_asset,                     # Send asset to another user
            "GET_PROFILE": self.handle_get_profile,             # Get user profile (anonymous)
        }
    
    def process_message(self, message):
        """Parse and handle incoming message"""
        try:
            parts = message.split('|')
            command = parts[0].strip()
            
            if command not in self.handlers:
                self.Print(f"❌ Unknown command: {command}", 40)
                self.Print(f"   Available commands: {', '.join(self.handlers.keys())}", 30)
                return f"ERR02|Unknown command: {command}"
            
            handler = self.handlers[command]
            self.Print(f"🔹 Processing command: {command}", 20)
            return handler(parts[1:])
        except Exception as e:
            self.Print(f"❌ Error processing message: {e}", 40)
            return f"ERR99|{str(e)}"
    
    def handle_start(self, params):
        """Protocol Message 1: START - Initialize connection"""
        self.Print("✅ START message received - accepting connection", 20)
        return "ACCPT|Connection accepted"
    
    def handle_login(self, params):
        """Protocol Message: LOGIN - Email/Password authentication
        Format: LOGIN|email|password
        Returns: OK|username|email or ERR|error_message
        """
        if len(params) < 2:
            self.Print("❌ Invalid login format", 40)
            return "ERR01|Invalid login format"
        
        email = params[0].strip()
        password = params[1].strip()
        
        # Validate email format
        if not email or '|' in email or ' ' in email:
            self.Print(f"❌ Invalid email format: {email}", 40)
            return "ERR01|Invalid email format"
        
        try:
            # Search users by email
            all_users = self.db.get_users()
            
            for username, user_obj in all_users.items():
                if user_obj.get_email() == email:
                    # Found user with this email, check password
                    if user_obj.is_same_password(password):
                        self.username = username
                        self.is_authenticated = True
                        self.Print(f"✅ [RECV] LOGIN|{email}|***", 20)
                        self.Print(f"✅ User {username} ({email}) logged in", 20)
                        return f"OK|{username}|{email}"
                    else:
                        self.Print(f"❌ Wrong password for {email}", 40)
                        return "ERR01|Invalid email or password"
            
            self.Print(f"❌ Email {email} not found in system", 40)
            return "ERR01|Invalid email or password"
        
        except Exception as e:
            self.Print(f"❌ Login error: {e}", 40)
            return f"ERR99|{str(e)}"
    
    def handle_signup(self, params):
        """Protocol Message: SIGNUP - User registration (Anonymous profile)
        Format: SIGNUP|username|password|email
        Returns: OK|username or ERR|error_message
        """
        if len(params) < 3:
            self.Print("❌ Invalid signup format", 40)
            return "ERR10|Invalid signup format: SIGNUP|username|password|email"
        
        username = params[0].strip()
        password = params[1].strip()
        email = params[2].strip()
        
        # Validate fields - no pipes or spaces
        if '|' in username or '|' in password or '|' in email:
            self.Print(f"❌ Invalid characters in signup fields", 40)
            return "ERR10|Fields cannot contain '|'"
        
        if username != params[0] or password != params[1] or email != params[2]:
            self.Print(f"❌ Fields have leading/trailing spaces", 40)
            return "ERR10|Fields cannot have leading/trailing spaces"
        
        # Validate inputs
        if not username or not password or not email:
            self.Print(f"❌ Missing required fields for signup", 40)
            return "ERR10|Missing required fields"
        
        # Username validation: 3-20 chars, alphanumeric + underscore
        import re
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
            self.Print(f"❌ Invalid username format: {username}", 40)
            return "ERR10|Username: 3-20 chars, alphanumeric + underscore only"
        
        # Password validation: min 6 chars
        if len(password) < 6:
            self.Print(f"❌ Password too short", 40)
            return "ERR10|Password must be at least 6 characters"
        
        # Email validation
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            self.Print(f"❌ Invalid email format: {email}", 40)
            return "ERR10|Invalid email format"
        
        # Check if username or email already exists
        all_users = self.db.get_users()
        if username in all_users:
            self.Print(f"❌ Username {username} already exists", 40)
            return "ERR10|Username already taken"
        
        for u in all_users.values():
            if u.get_email() == email:
                self.Print(f"❌ Email {email} already registered", 40)
                return "ERR10|Email already registered"
        
        # Create new user (anonymous profile = no profile pic, just username)
        if self.db.add_user(username, password, email):
            self.Print(f"✅ User {username} ({email}) signed up", 20)
            return f"OK|{username}"
        else:
            self.Print(f"❌ Signup failed for {username}", 40)
            return "ERR99|Signup failed"
    
    def handle_send_code(self, params):
        """Protocol Message: SEND_CODE - Send OTP code for password reset
        Format: SEND_CODE|email
        Returns: OK|otp_sent or ERR|error_message
        """
        if len(params) < 1:
            self.Print("❌ Invalid SEND_CODE format", 40)
            return "ERR04|Invalid format: SEND_CODE|email"
        
        email = params[0].strip()
        
        # Validate email format
        if not email or '|' in email or ' ' in email:
            self.Print(f"❌ Invalid email format", 40)
            return "ERR04|Invalid email format"
        
        # Find user by email
        all_users = self.db.get_users()
        user_obj = None
        username = None
        
        for uname, u in all_users.items():
            if u.get_email() == email:
                user_obj = u
                username = uname
                break
        
        if not user_obj:
            self.Print(f"❌ Email {email} not registered", 40)
            return "ERR04|Email not found in system"
        
        # Generate OTP
        otp = user_obj.generate_otp()
        self.Print(f"📧 Generated OTP {otp} for {email}", 20)
        
        # TODO: In production, send real email with OTP
        # For now, log it to console
        self.Print(f"🔐 [DEV] OTP Code: {otp}", 30)
        
        # Update user in database
        self.db.update_info(username, user_obj)
        
        return "OK|otp_sent"
    
    def handle_verify_code(self, params):
        """Protocol Message: VERIFY_CODE - Verify OTP code
        Format: VERIFY_CODE|email|otp_code
        Returns: OK|token or ERR|error_message
        """
        if len(params) < 2:
            self.Print("❌ Invalid VERIFY_CODE format", 40)
            return "ERR08|Invalid format: VERIFY_CODE|email|otp_code"
        
        email = params[0].strip()
        otp_code = params[1].strip()
        
        # Validate inputs
        if not email or not otp_code or '|' in email or '|' in otp_code:
            self.Print(f"❌ Invalid verify code inputs", 40)
            return "ERR08|Invalid input format"
        
        # Find user by email
        all_users = self.db.get_users()
        user_obj = None
        username = None
        
        for uname, u in all_users.items():
            if u.get_email() == email:
                user_obj = u
                username = uname
                break
        
        if not user_obj:
            self.Print(f"❌ Email {email} not found", 40)
            return "ERR08|Email not found"
        
        # Verify OTP
        if user_obj.verify_otp(otp_code):
            self.Print(f"✅ OTP verified for {email}", 20)
            # Update user in database
            self.db.update_info(username, user_obj)
            # Generate reset token
            token = f"RESET_{username}_{int(time.time())}"
            return f"OK|{token}"
        else:
            self.Print(f"❌ Invalid or expired OTP for {email}", 40)
            return "ERR08|Invalid or expired OTP"
    
    def handle_update_password(self, params):
        """Protocol Message: UPDATE_PASSWORD - Change user password (after OTP verification)
        Format: UPDATE_PASSWORD|email|new_password
        Returns: OK or ERR|error_message
        """
        if len(params) < 2:
            self.Print("❌ Invalid UPDATE_PASSWORD format", 40)
            return "ERR07|Invalid format: UPDATE_PASSWORD|email|new_password"
        
        email = params[0].strip()
        new_password = params[1].strip()
        
        # Validate inputs
        if not email or not new_password or '|' in email or '|' in new_password:
            self.Print(f"❌ Invalid password update inputs", 40)
            return "ERR07|Invalid input format"
        
        # Password must be min 6 chars
        if len(new_password) < 6:
            self.Print(f"❌ New password too short", 40)
            return "ERR07|Password must be at least 6 characters"
        
        # Find user by email
        all_users = self.db.get_users()
        user_obj = None
        username = None
        
        for uname, u in all_users.items():
            if u.get_email() == email:
                user_obj = u
                username = uname
                break
        
        if not user_obj:
            self.Print(f"❌ Email {email} not found", 40)
            return "ERR07|Email not found"
        
        # Update password
        user_obj.set_password(new_password)
        self.db.update_info(username, user_obj)
        
        self.Print(f"🔑 Password updated for {email}", 20)
        return "OK|Password updated successfully"
    
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

    def handle_get_items_paginated(self, params):
        """Protocol Message: GET_ITEMS_PAGINATED - Get marketplace items with pagination
        Format: GET_ITEMS_PAGINATED|limit[|lastTimestamp]
        
        Lazy scrolling: Client sends cursor (lastTimestamp) to get next batch
        Server returns items with timestamps so client can request next batch
        """
        import json
        from marketplace_db import MarketplaceDB
        
        if len(params) < 1:
            self.Print(f"[RECV] GET_ITEMS_PAGINATED - Invalid format", 40)
            return "ERR01|Invalid format"
        
        try:
            limit = int(params[0].strip())
            lastTimestamp = None
            
            if len(params) > 1 and params[1].strip():
                lastTimestamp = float(params[1].strip())
            
            # Log incoming request
            self.Print(f"[RECV] GET_ITEMS_PAGINATED|{limit}|{lastTimestamp}", 20)
            
            # Query marketplace database
            try:
                db = MarketplaceDB()
                
                if lastTimestamp:
                    # Get items before this timestamp for pagination
                    items = db.get_items_before_timestamp(lastTimestamp, limit)
                else:
                    # Get latest items
                    items = db.get_latest_items(limit)
                
                if items:
                    # Convert tuples/rows to dictionaries
                    items_list = []
                    for item in items:
                        # Assuming item is a tuple: (id, asset_name, username, url, cost, file_type, timestamp)
                        if isinstance(item, dict):
                            items_list.append(item)
                        elif isinstance(item, (tuple, list)) and len(item) >= 7:
                            items_list.append({
                                'id': item[0],
                                'asset_name': item[1],
                                'username': item[2],
                                'url': item[3],
                                'cost': item[4],
                                'file_type': item[5],
                                'timestamp': item[6]
                            })
                    
                    response = f"OK|{json.dumps(items_list)}"
                    self.Print(f"[SEND] OK|{len(items_list)} items", 20)
                    self.Print(f"📦 Returned {len(items_list)} items (last timestamp: {items_list[-1].get('timestamp') if items_list else 'N/A'})", 20)
                    return response
                else:
                    response = "OK|[]"
                    self.Print(f"[SEND] OK|0 items (no more items)", 20)
                    return response
                    
            except Exception as db_error:
                self.Print(f"❌ Database error: {db_error}", 40)
                return f"ERR03|Database error: {str(db_error)}"
        
        except ValueError as ve:
            self.Print(f"[RECV] GET_ITEMS_PAGINATED - Invalid parameters: {ve}", 40)
            return "ERR01|Invalid parameters"
        except Exception as e:
            self.Print(f"❌ Error processing GET_ITEMS_PAGINATED: {e}", 40)
            return f"ERR99|{str(e)}"

    def handle_buy_asset(self, params):
        """
        BUY - Purchase an asset from marketplace
        Format: BUY|asset_id|username|amount
        """
        if len(params) < 3:
            self.Print(f"[RECV] BUY - Invalid format", 40)
            return "ERR01|Invalid format: BUY|asset_id|username|amount"
        
        try:
            asset_id = params[0].strip()
            username = params[1].strip()
            amount = float(params[2].strip())
            
            self.Print(f"💳 Processing purchase: {username} buying asset {asset_id} for {amount}", 20)
            
            # TODO: Implement transaction logic
            # - Validate asset exists
            # - Check buyer balance/payment method
            # - Record transaction in blockchain
            # - Update asset ownership
            transaction_id = f"TXN_{asset_id}_{username}_{int(time.time())}"
            
            self.Print(f"✅ Purchase successful: {transaction_id}", 20)
            return f"OK|{transaction_id}"
            
        except ValueError as ve:
            self.Print(f"[RECV] BUY - Invalid parameters: {ve}", 40)
            return "ERR01|Invalid amount format"
        except Exception as e:
            self.Print(f"❌ Error processing BUY: {e}", 40)
            return f"ERR99|{str(e)}"

    def handle_send_asset(self, params):
        """
        SEND - Send purchased asset to another user
        Format: SEND|asset_id|sender_username|receiver_username
        """
        if len(params) < 3:
            self.Print(f"[RECV] SEND - Invalid format", 40)
            return "ERR01|Invalid format: SEND|asset_id|sender|receiver"
        
        try:
            asset_id = params[0].strip()
            sender_username = params[1].strip()
            receiver_username = params[2].strip()
            
            self.Print(f"📤 Processing asset send: {sender_username} → {receiver_username} (asset: {asset_id})", 20)
            
            # TODO: Implement asset transfer logic
            # - Validate sender owns asset
            # - Validate receiver exists
            # - Record transfer in blockchain
            # - Update asset ownership
            transaction_id = f"SEND_{asset_id}_{sender_username}_{receiver_username}_{int(time.time())}"
            
            self.Print(f"✅ Asset sent successfully: {transaction_id}", 20)
            return f"OK|{transaction_id}"
            
        except Exception as e:
            self.Print(f"❌ Error processing SEND: {e}", 40)
            return f"ERR99|{str(e)}"

    def handle_get_profile(self, params):
        """
        GET_PROFILE - Get user profile (anonymous)
        Format: GET_PROFILE|username
        Returns: OK|username|email|created_at or ERR|error_message
        """
        if len(params) < 1:
            self.Print(f"[RECV] GET_PROFILE - Invalid format", 40)
            return "ERR01|Invalid format: GET_PROFILE|username"
        
        try:
            username = params[0].strip()
            
            if not username or '|' in username:
                self.Print(f"❌ Invalid username format", 40)
                return "ERR01|Invalid username"
            
            # Find user
            all_users = self.db.get_users()
            if username not in all_users:
                self.Print(f"❌ User {username} not found", 40)
                return "ERR02|User not found"
            
            user_obj = all_users[username]
            email = user_obj.get_email()
            
            # For now, use user creation time as profile created_at
            # TODO: Store actual profile creation time
            created_at = int(time.time())
            
            self.Print(f"✅ Profile retrieved for {username}", 20)
            return f"OK|{username}|{email}|{created_at}"
            
        except Exception as e:
            self.Print(f"❌ Error processing GET_PROFILE: {e}", 40)
            return f"ERR99|{str(e)}"


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
                broadcast_sock.settimeout(1.0)  # 1 second timeout to allow checking is_running
                broadcast_sock.bind(('0.0.0.0', 12345))
                
                self.Print("📡 Broadcast listener started on port 12345", 20)
                
                while self.is_running:
                    try:
                        data, addr = broadcast_sock.recvfrom(1024)
                        message = data.decode('utf-8').strip()
                        
                        if message == "WHRSRV":
                            # Get the local IP address (not 0.0.0.0)
                            try:
                                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                s.connect(("8.8.8.8", 53))  # Use DNS port instead of HTTP
                                local_ip = s.getsockname()[0]
                                s.close()
                            except:
                                local_ip = self.server_ip  # Fallback to configured IP
                            
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
                        
                        # Handle client in separate thread (non-blocking)
                        client_thread = threading.Thread(
                            target=self.handle_client,
                            args=(ssl_sock, addr),
                            daemon=True
                        )
                        client_thread.start()
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
