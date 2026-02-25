"""
Aurex Blockchain Server - Handles client connections and marketplace (ORM: DB/marketplace.db)
One persistent connection per client, event-based processing

PROTOCOL SPECIFICATION
======================
All client-server communication uses TLS on port 23456 with 2-byte length prefix.

Message Format: [2-byte length][protocol command]

Supported Commands:
  1. START - Connection initialization
     Send: START|Client_Flutter_App
     Recv: ACCPT|Connection accepted
  
  2. LOGIN - User authentication (by USERNAME)
     Send: LOGIN|username|password
     Recv: OK|username or ERR|error_message
  
  3. SIGNUP - User registration (by USERNAME)
     Send: SIGNUP|username|password
     Recv: OK or ERR|error_message
  
  4. SEND_CODE - Request password reset OTP code via username
     Send: SEND_CODE|username
     Recv: OK|code_sent or ERR|error_message
  
  5. VERIFY_CODE - Verify OTP code for password reset
     Send: VERIFY_CODE|username|otp_code
     Recv: OK|token or ERR|error_message
  
  6. UPDATE_PASSWORD - Change user password (after OTP verification)
     Send: UPDATE_PASSWORD|username|new_password
     Recv: OK or ERR|error_message
  
  7. LOGOUT - User logout
     Send: LOGOUT|username
     Recv: OK or ERR|error_message
  
  8. UPLOAD_INIT - Start chunked upload session
     Send: UPLOAD_INIT|base64(json)
     Recv: OK|upload_id|chunk_size or ERR|error_message

  9. UPLOAD_CHUNK - Send file chunk (base64)
     Send: UPLOAD_CHUNK|upload_id|seq|total|base64(chunk)
     Recv: OK|seq or ERR|error_message

  10. UPLOAD_FINISH - Finalize upload (Drive + DB)
      Send: UPLOAD_FINISH|upload_id
      Recv: OK|asset_name|drive_url or ERR|error_message

  11. UPLOAD_ABORT - Cancel an in-progress upload
      Send: UPLOAD_ABORT|upload_id
      Recv: OK|message or ERR|error_message

  12. UPLOAD - Legacy direct-URL upload/register
      Send: UPLOAD|asset_name|username|google_drive_url|file_type|cost
      Recv: OK|asset_id or ERR|error_message
  
  13. GET_ITEMS - Get all marketplace items
     Send: GET_ITEMS
     Recv: OK|item1|item2|... or ERR|error_message
  
  14. GET_ITEMS_PAGINATED - Lazy scrolling with timestamp cursor
      Send: GET_ITEMS_PAGINATED|limit[|timestamp]
      Recv: OK|item1|item2|... or ERR|error_message
  
  15. BUY - Purchase an asset from marketplace
      Send: BUY|asset_id|username|amount
      Recv: OK|PENDING|transaction_id or ERR|error_message
  
  16. SEND - Send purchased asset to another user
      Send: SEND|asset_id|sender_username|receiver_username
      Recv: OK|transaction_id or ERR|error_message
  
  17. GET_PROFILE - Get user profile (anonymous - username only)
      Send: GET_PROFILE|username
      Recv: OK|username|email|created_at or ERR|error_message

  18. GET_USER_BY_EMAIL - Look up username by email (e.g. for Google sign-in)
      Send: GET_USER_BY_EMAIL|email
      Recv: OK|username or ERR|error_message

  19. GET_TX_STATUS - Check blockchain purchase status
      Send: GET_TX_STATUS|tx_id
      Recv: OK|STATUS|message or ERR|error_message

  20. GET_ITEMS_BY_USER - Get assets owned by a user
      Send: GET_ITEMS_BY_USER|username
      Recv: OK|items_json or ERR|error_message

  21. GET_WALLET - Get wallet balance for a user
      Send: GET_WALLET|username
      Recv: OK|balance|updated_at or ERR|error_message
"""

import base64
import datetime
import json
import logging
import os
import queue
import random
import socket
import ssl as ssl_module
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from config import (
    SERVER_HOST, SERVER_PORT, SERVER_IP,
    BROADCAST_PORT, SSL_CERT_FILE, SSL_KEY_FILE,
    LOGGING_LEVEL, BLOCK_CONFIRMATION_PORT,
    GATEWAY_HOST, GATEWAY_PORT,
    GOOGLE_DRIVE_PARENT_FOLDER_ID, GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE,
    GOOGLE_DRIVE_UPLOAD_ACCOUNT_EMAIL,
    UPLOAD_TMP_DIR, UPLOAD_CHUNK_SIZE,
)
from classes import PROTO, CustomLogger
from DB_ORM import MarketplaceDB
from google_drive_uploader import upload_file_to_drive

server_logger = CustomLogger("server", LOGGING_LEVEL).logger


@dataclass
class UploadSession:
    """Track a chunked upload session per client."""
    upload_id: str
    username: str
    asset_name: str
    description: str
    file_type: str
    cost: float
    file_size: int
    original_name: str
    temp_path: str
    total_chunks: int = 0
    received_chunks: int = 0
    next_seq: int = 0
    bytes_received: int = 0
    created_at: float = field(default_factory=time.time)


class ClientSession:
    """Represents one authenticated client connection"""
    def __init__(self, sock, addr, logging_level, server):
        self.socket = sock
        self.address = addr
        self.server = server
        
        # Pass socket directly to PROTO constructor instead of assigning afterward
        self.proto = PROTO("ClientSession", logging_level=logging_level, cln_sock=sock)
        
        self.logger = CustomLogger(f"Session-{addr[0]}:{addr[1]}", logging_level)
        self.Print = self.logger.Print
        
        self.username = None
        self.is_authenticated = False
        self.is_connected = True
        self.db = MarketplaceDB()  # ORM: DB/marketplace.db (users + marketplace_items)
        self.upload_sessions = {}

        # Ensure upload temp directory exists
        self.upload_tmp_dir = Path(UPLOAD_TMP_DIR)
        if not self.upload_tmp_dir.is_absolute():
            self.upload_tmp_dir = (Path(__file__).parent / self.upload_tmp_dir).resolve()
        self.upload_tmp_dir.mkdir(parents=True, exist_ok=True)

        self.handlers = {
            "START": self.handle_start,
            "LOGIN": self.handle_login,
            "SIGNUP": self.handle_signup,
            "GET_USER_BY_EMAIL": self.handle_get_user_by_email,
            "SEND_CODE": self.handle_send_code,
            "VERIFY_CODE": self.handle_verify_code,
            "UPDATE_PASSWORD": self.handle_update_password,
            "LOGOUT": self.handle_logout,
            "UPLOAD": self.handle_log_asset,
            "UPLOAD_INIT": self.handle_upload_init,
            "UPLOAD_CHUNK": self.handle_upload_chunk,
            "UPLOAD_FINISH": self.handle_upload_finish,
            "UPLOAD_ABORT": self.handle_upload_abort,
            "GET_ITEMS": self.handle_asset_list,
            "GET_ITEMS_PAGINATED": self.handle_get_items_paginated,
            "BUY": self.handle_buy_asset,
            "SEND": self.handle_send_asset,
            "GET_PROFILE": self.handle_get_profile,
            "GET_TX_STATUS": self.handle_get_tx_status,
            "GET_ITEMS_BY_USER": self.handle_get_items_by_user,
            "GET_WALLET": self.handle_get_wallet,
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
        """Protocol Message: LOGIN - Username/Password authentication
        Format: LOGIN|username|password
        Returns: OK|username or ERR|error_message
        """
        if len(params) < 2:
            self.Print("❌ Invalid login format", 40)
            return "ERR01|Invalid login format"
        
        username = params[0].strip()
        password = params[1].strip()
        
        # Validate username format
        if not username or '|' in username or ' ' in username:
            self.Print(f"❌ Invalid username format: {username}", 40)
            return "ERR01|Invalid username format"
        
        try:
            user_obj = self.db.get_user(username)
            if user_obj and user_obj.verify_password(password):
                self.username = username
                self.is_authenticated = True
                self.Print(f"✅ [RECV] LOGIN|{username}|***", 20)
                self.Print(f"✅ User {username} logged in", 20)
                return f"OK|{username}"
            self.Print(f"❌ Invalid credentials for {username}", 40)
            return "ERR01|user not found"
        except Exception as e:
            self.Print(f"❌ Login error: {e}", 40)
            return f"ERR99|{str(e)}"
    
    def handle_signup(self, params):
        """Protocol Message: SIGNUP - User registration
        Format: SIGNUP|username|password
        Returns: OK|username or ERR|error_message
        """
        if len(params) < 2:
            self.Print("❌ Invalid signup format", 40)
            return "ERR10|Invalid signup format: SIGNUP|username|password"
        
        username = params[0].strip()
        password = params[1].strip()
        
        # Validate fields - no pipes or spaces
        if '|' in username or '|' in password:
            self.Print(f"❌ Invalid characters in signup fields", 40)
            return "ERR10|Fields cannot contain '|'"
        
        if username != params[0] or password != params[1]:
            self.Print(f"❌ Fields have leading/trailing spaces", 40)
            return "ERR10|Fields cannot have leading/trailing spaces"
        
        # Validate inputs
        if not username or not password:
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
        
        email = f"{username}@aurex.local"
        success, message = self.db.add_user(username, password, email)
        if success:
            self.Print(f"✅ User {username} signed up", 20)
            return f"OK|{username}"
        self.Print(f"❌ Signup failed: {message}", 40)
        return f"ERR10|{message}"

    def handle_get_user_by_email(self, params):
        """GET_USER_BY_EMAIL - Look up username by email (e.g. for Google sign-in).
        Format: GET_USER_BY_EMAIL|email
        Returns: OK|username or ERR|error_message
        """
        if len(params) < 1:
            return "ERR01|Invalid format: GET_USER_BY_EMAIL|email"
        email = params[0].strip()
        if not email or '|' in email:
            return "ERR01|Invalid email format"
        user_obj = self.db.get_user_by_email(email)
        if user_obj:
            self.Print(f"✅ User by email {email}: {user_obj.username}", 20)
            return f"OK|{user_obj.username}"
        self.Print(f"❌ No user for email {email}", 40)
        return "ERR02|User not found"

    def handle_send_code(self, params):
        """Protocol Message: SEND_CODE - Send OTP code for password reset
        Format: SEND_CODE|email
        Returns: OK|otp_sent or ERR|error_message
        """
        if len(params) < 1:
            self.Print("❌ Invalid SEND_CODE format", 40)
            return "ERR04|Invalid format: SEND_CODE|email"
        
        email = params[0].strip()
        
        if not email or '|' in email or ' ' in email:
            self.Print(f"❌ Invalid email format", 40)
            return "ERR04|Invalid email format"
        user_obj = self.db.get_user_by_email(email)
        if not user_obj:
            self.Print(f"❌ Email {email} not registered", 40)
            return "ERR04|Email not found in system"
        otp = str(random.randint(100000, 999999))
        user_obj.set_verification_code(otp)
        user_obj.set_reset_time((datetime.datetime.now() + datetime.timedelta(minutes=5)).isoformat())
        self.db.update_user(user_obj.username, user_obj)
        self.Print(f"📧 Generated OTP {otp} for {email}", 20)
        self.Print(f"🔐 [DEV] OTP Code: {otp}", 30)
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
        
        if not email or not otp_code or '|' in email or '|' in otp_code:
            self.Print(f"❌ Invalid verify code inputs", 40)
            return "ERR08|Invalid input format"
        user_obj = self.db.get_user_by_email(email)
        if not user_obj:
            self.Print(f"❌ Email {email} not found", 40)
            return "ERR08|Email not found"
        if user_obj.is_code_match_and_available(datetime.datetime.now(), otp_code):
            user_obj.is_verified = True
            self.db.update_user(user_obj.username, user_obj)
            self.Print(f"✅ OTP verified for {email}", 20)
            return f"OK|RESET_{user_obj.username}_{int(time.time())}"
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
        
        if not email or not new_password or '|' in email or '|' in new_password:
            self.Print(f"❌ Invalid password update inputs", 40)
            return "ERR07|Invalid input format"
        if len(new_password) < 6:
            self.Print(f"❌ New password too short", 40)
            return "ERR07|Password must be at least 6 characters"
        user_obj = self.db.get_user_by_email(email)
        if not user_obj:
            self.Print(f"❌ Email {email} not found", 40)
            return "ERR07|Email not found"
        user_obj.set_password(new_password)
        self.db.update_user(user_obj.username, user_obj)
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

    def _normalize_file_type(self, file_type: str) -> str:
        """Normalize file type to a supported extension."""
        normalized = (file_type or "").strip().lower()
        if normalized == "jpeg":
            normalized = "jpg"
        if normalized == "image":
            normalized = "jpg"
        return normalized

    def _validate_file_signature(self, file_type: str, first_bytes: bytes) -> bool:
        """Validate PNG/JPG magic bytes."""
        if file_type == "png":
            return first_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        if file_type == "jpg":
            return first_bytes.startswith(b"\xff\xd8\xff")
        return False

    def _cleanup_upload(self, upload_id: str) -> None:
        """Remove temp file and session data for a given upload."""
        session = self.upload_sessions.pop(upload_id, None)
        if not session:
            return
        try:
            if os.path.exists(session.temp_path):
                os.remove(session.temp_path)
        except Exception:
            pass
    
    def handle_log_asset(self, params):
        """Protocol Message: UPLOAD - Legacy direct-URL upload
        Format: UPLOAD|asset_name|username|google_drive_url|file_type|cost
        """
        if not self.is_authenticated:
            return "ERR03|Not authenticated"
        
        if len(params) < 5:
            self.Print(f"[RECV] UPLOAD - Invalid format, got {len(params)} params", 40)
            return "ERR01|Invalid format: UPLOAD|asset_name|username|url|file_type|cost"
        
        try:
            asset_name = params[0].strip()
            username = params[1].strip()
            url = params[2].strip()
            file_type = params[3].strip()
            cost = float(params[4].strip())
            
            # Ensure authenticated user is uploading for their own account
            if username != self.username:
                return "ERR02|Cannot upload on behalf of another user"
            
            # Validate inputs
            if not asset_name or not username or not url or not file_type or cost < 0:
                return "ERR01|Invalid parameters"
            
            normalized_type = self._normalize_file_type(file_type)
            if normalized_type not in ['jpg', 'png']:
                return "ERR01|Invalid file type. Supported: jpg, png"
            
            # Add to marketplace database (ORM: DB/marketplace.db)
            marketplace_db = MarketplaceDB()
            success, message = marketplace_db.add_marketplace_item(asset_name, username, url, normalized_type, cost)
            
            if success:
                self.Print(f"✅ Asset uploaded: {asset_name} by {username} - \\${cost}", 20)
                return f"OK|Asset '{asset_name}' uploaded successfully"
            else:
                self.Print(f"❌ Failed to upload asset: {message}", 40)
                return f"ERR03|{message}"
                
        except ValueError as ve:
            return "ERR01|Invalid cost format"
        except Exception as e:
            self.Print(f"❌ Error processing UPLOAD: {e}", 40)
            return f"ERR99|{str(e)}"

    def handle_upload_init(self, params):
        """
        Protocol: UPLOAD_INIT - Start a chunked upload session.
        Format: UPLOAD_INIT|base64(json)
        Response: OK|upload_id|chunk_size or ERR|message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: UPLOAD_INIT|base64(json)"
        try:
            payload = base64.b64decode(params[0].encode("utf-8"))
            data = json.loads(payload.decode("utf-8"))
        except Exception:
            return "ERR01|Invalid init payload"

        asset_name = str(data.get("asset_name", "")).strip()
        username = str(data.get("username", "")).strip()
        description = str(data.get("description", "")).strip()
        file_type = self._normalize_file_type(data.get("file_type", ""))
        original_name = str(data.get("original_name", "")).strip()
        file_size = int(data.get("file_size", 0) or 0)
        try:
            cost = float(data.get("cost", 0))
        except Exception:
            cost = -1

        if username != self.username:
            return "ERR02|Unauthorized"
        if not asset_name or not username or cost <= 0 or file_size <= 0:
            return "ERR01|Invalid parameters"
        if file_type not in ("jpg", "png"):
            return "ERR01|Invalid file type. Supported: jpg, png"

        upload_id = uuid.uuid4().hex
        temp_path = str(self.upload_tmp_dir / f"upload_{upload_id}.bin")

        session = UploadSession(
            upload_id=upload_id,
            username=username,
            asset_name=asset_name,
            description=description,
            file_type=file_type,
            cost=cost,
            file_size=file_size,
            original_name=original_name or f"{asset_name}.{file_type}",
            temp_path=temp_path,
        )
        self.upload_sessions[upload_id] = session

        return f"OK|{upload_id}|{UPLOAD_CHUNK_SIZE}"

    def handle_upload_chunk(self, params):
        """
        Protocol: UPLOAD_CHUNK - Send a file chunk.
        Format: UPLOAD_CHUNK|upload_id|seq|total|base64(chunk)
        Response: OK|seq or ERR|message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 4:
            return "ERR01|Invalid format: UPLOAD_CHUNK|upload_id|seq|total|data"

        upload_id = params[0].strip()
        session = self.upload_sessions.get(upload_id)
        if not session:
            return "ERR04|Upload session not found"
        if session.username != self.username:
            return "ERR02|Unauthorized"

        try:
            seq = int(params[1])
            total = int(params[2])
        except Exception:
            return "ERR01|Invalid chunk metadata"

        if total <= 0 or seq < 0:
            return "ERR01|Invalid chunk indices"
        if session.total_chunks and session.total_chunks != total:
            return "ERR01|Total chunk mismatch"
        session.total_chunks = total

        if seq != session.next_seq:
            return f"ERR05|Out of order chunk (expected {session.next_seq})"

        try:
            chunk_bytes = base64.b64decode(params[3].encode("utf-8"))
        except Exception:
            return "ERR01|Invalid chunk encoding"

        if seq == 0 and not self._validate_file_signature(session.file_type, chunk_bytes):
            self._cleanup_upload(upload_id)
            return "ERR06|Invalid file signature"

        session.bytes_received += len(chunk_bytes)
        if session.bytes_received > session.file_size:
            self._cleanup_upload(upload_id)
            return "ERR06|File size mismatch"

        try:
            with open(session.temp_path, "ab") as handle:
                handle.write(chunk_bytes)
        except Exception as e:
            self._cleanup_upload(upload_id)
            return f"ERR99|Failed to write chunk: {e}"

        session.received_chunks += 1
        session.next_seq += 1
        return f"OK|{seq}"

    def handle_upload_finish(self, params):
        """
        Protocol: UPLOAD_FINISH - Finalize upload, push to Drive, register asset.
        Format: UPLOAD_FINISH|upload_id
        Response: OK|asset_name|url or ERR|message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: UPLOAD_FINISH|upload_id"

        upload_id = params[0].strip()
        session = self.upload_sessions.get(upload_id)
        if not session:
            return "ERR04|Upload session not found"
        if session.username != self.username:
            return "ERR02|Unauthorized"
        if session.total_chunks == 0 or session.received_chunks != session.total_chunks:
            return "ERR06|Upload incomplete"

        try:
            actual_size = os.path.getsize(session.temp_path)
        except Exception:
            actual_size = 0
        if actual_size != session.file_size:
            self._cleanup_upload(upload_id)
            return "ERR06|File size mismatch"

        file_name = f"{session.asset_name}.{session.file_type}"
        try:
            if GOOGLE_DRIVE_UPLOAD_ACCOUNT_EMAIL:
                self.Print(
                    f"Drive upload account: {GOOGLE_DRIVE_UPLOAD_ACCOUNT_EMAIL}",
                    10,
                )
            drive_url = upload_file_to_drive(
                session.temp_path,
                file_name,
                session.description,
                parent_folder_id=GOOGLE_DRIVE_PARENT_FOLDER_ID,
                service_account_file=GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE,
                username=session.username,
                asset_name=session.asset_name,
            )
        except Exception as e:
            self._cleanup_upload(upload_id)
            return f"ERR03|Drive upload failed: {e}"

        try:
            marketplace_db = MarketplaceDB()
            success, message = marketplace_db.add_marketplace_item(
                session.asset_name,
                session.username,
                drive_url,
                session.file_type,
                session.cost,
                session.description,
            )
        except Exception as e:
            self._cleanup_upload(upload_id)
            return f"ERR03|DB error: {e}"

        self._cleanup_upload(upload_id)
        if not success:
            return f"ERR03|{message}"
        self.Print(f"✅ Asset uploaded: {session.asset_name} by {session.username} - ${session.cost}", 20)
        return f"OK|{session.asset_name}|{drive_url}"

    def handle_upload_abort(self, params):
        """
        Protocol: UPLOAD_ABORT - Cancel an in-progress upload.
        Format: UPLOAD_ABORT|upload_id
        """
        if len(params) < 1:
            return "ERR01|Invalid format: UPLOAD_ABORT|upload_id"
        upload_id = params[0].strip()
        self._cleanup_upload(upload_id)
        return "OK|Upload aborted"
    
    def handle_asset_list(self, params):
        """Protocol Message: GET_ITEMS - Get all marketplace items
        Format: GET_ITEMS
        Returns: OK|items_json or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"

        try:
            import json
            items = self.db.get_all_items()
            response = f"OK|{json.dumps(items)}"
            self.Print(f"📋 GET_ITEMS: returned {len(items)} items", 20)
            return response
        except Exception as e:
            self.Print(f"? Error processing GET_ITEMS: {e}", 40)
            return f"ERR03|Error getting items: {str(e)}"

    def handle_get_items_paginated(self, params):
        """Protocol Message: GET_ITEMS_PAGINATED - Get marketplace items with pagination
        Format: GET_ITEMS_PAGINATED|limit[|lastTimestamp] (lastTimestamp = ISO string from last item)
        """
        import json
        
        if len(params) < 1:
            self.Print(f"[RECV] GET_ITEMS_PAGINATED - Invalid format", 40)
            return "ERR01|Invalid format"
        
        try:
            limit = int(params[0].strip())
            lastTimestamp = params[1].strip() if len(params) > 1 and params[1].strip() else None
            
            self.Print(f"[RECV] GET_ITEMS_PAGINATED|{limit}|{lastTimestamp}", 20)
            
            try:
                db = MarketplaceDB()
                if lastTimestamp:
                    items = db.get_items_before_timestamp(lastTimestamp, limit)
                else:
                    items = db.get_latest_items(limit)
                
                if items:
                    items_list = items if isinstance(items[0], dict) else [
                        {'id': r[0], 'asset_name': r[1], 'description': r[2], 'username': r[3], 'url': r[4],
                         'file_type': r[5], 'cost': r[6], 'timestamp': r[7], 'created_at': r[8]}
                        for r in items
                    ]
                    response = f"OK|{json.dumps(items_list)}"
                    self.Print(f"[SEND] OK|{len(items_list)} items", 20)
                    return response
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
        if not self.is_authenticated:
            return "ERR03|Not authenticated"
        if len(params) < 3:
            self.Print(f"[RECV] BUY - Invalid format", 40)
            return "ERR01|Invalid format: BUY|asset_id|username|amount"

        try:
            asset_id = params[0].strip()
            username = params[1].strip()
            amount = float(params[2].strip())

            self.Print(f"💳 Processing purchase: {username} buying asset {asset_id} for {amount}", 20)

            if username != self.username:
                return "ERR02|Cannot purchase on behalf of another user"

            item = self.db.get_item_by_id(asset_id)
            if not item:
                return "ERR02|Asset not found"

            seller = item.get('username')
            if seller == username:
                return "ERR02|Cannot buy your own asset"

            price = float(item.get('cost', 0))
            if abs(price - amount) > 0.01:
                return "ERR02|Price mismatch"

            wallet = self.db.get_wallet(username)
            if not wallet:
                return "ERR02|Wallet not found"
            if float(wallet.get('balance', 0)) < price:
                return "ERR02|Insufficient funds"

            tx_id = f"TXN_{asset_id}_{username}_{uuid.uuid4().hex[:8]}"
            purchase = {
                'tx_id': tx_id,
                'buyer': username,
                'seller': seller,
                'asset_id': asset_id,
                'asset_name': item.get('asset_name'),
                'amount': price,
                'timestamp': datetime.datetime.utcnow().isoformat(),
            }

            with self.server.tx_status_lock:
                self.server.tx_status[tx_id] = {
                    'status': 'queued',
                    'message': 'Queued for PoW',
                    'created_at': time.time(),
                    'asset_id': asset_id,
                    'buyer': username,
                    'seller': seller,
                    'amount': price,
                }
            self.server.tx_queue.put(purchase)

            self.Print(f"✅ Purchase queued for PoW: {tx_id}", 20)
            return f"OK|PENDING|{tx_id}"

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
            user_obj = self.db.get_user(username)
            if not user_obj:
                self.Print(f"❌ User {username} not found", 40)
                return "ERR02|User not found"
            self.Print(f"✅ Profile retrieved for {username}", 20)
            return f"OK|{username}|{user_obj.email}|{user_obj.created_at}"
        except Exception as e:
            self.Print(f"❌ Error processing GET_PROFILE: {e}", 40)
            return f"ERR99|{str(e)}"

    def handle_get_tx_status(self, params):
        """
        GET_TX_STATUS - Check transaction status
        Format: GET_TX_STATUS|tx_id
        Returns: OK|STATUS|message or ERR|error_message
        """
        if len(params) < 1:
            return "ERR01|Invalid format: GET_TX_STATUS|tx_id"
        tx_id = params[0].strip()
        if not tx_id:
            return "ERR01|Invalid tx_id"

        info = self.server._get_tx_info(tx_id)
        if not info:
            return "ERR02|Transaction not found"

        status = info.get('status', 'unknown')
        message = info.get('message', '')
        created_at = info.get('created_at', time.time())

        if status in ('queued', 'submitted'):
            if time.time() - created_at > self.server.tx_timeout_seconds:
                status = 'timeout'
                message = 'PoW Timeout after 10 mins'
                self.server._set_tx_status(tx_id, status, message)

        return f"OK|{status.upper()}|{message}"

    def handle_get_items_by_user(self, params):
        """
        GET_ITEMS_BY_USER - Get assets owned by a user
        Format: GET_ITEMS_BY_USER|username
        Returns: OK|items_json or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: GET_ITEMS_BY_USER|username"
        username = params[0].strip()
        if not username or '|' in username:
            return "ERR01|Invalid username"
        if username != self.username:
            return "ERR02|Unauthorized"
        try:
            items = self.db.get_items_by_username(username)
            return f"OK|{json.dumps(items)}"
        except Exception as e:
            return f"ERR03|Error getting items: {str(e)}"

    def handle_get_wallet(self, params):
        """
        GET_WALLET - Get wallet balance for a user
        Format: GET_WALLET|username
        Returns: OK|balance|updated_at or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: GET_WALLET|username"

        username = params[0].strip()
        if not username or '|' in username:
            return "ERR01|Invalid username"
        if username != self.username:
            return "ERR02|Unauthorized"

        try:
            self.db.ensure_wallet(username, 100)
            wallet = self.db.get_wallet(username)
            if not wallet:
                return "ERR02|Wallet not found"
            balance = wallet.get('balance', 0)
            updated_at = wallet.get('updated_at') or ''
            return f"OK|{balance}|{updated_at}"
        except Exception as e:
            return f"ERR03|Error getting wallet: {str(e)}"


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
        self.db = MarketplaceDB()

        # Purchase -> gateway queue + status tracking
        self.tx_queue = queue.Queue()
        self.tx_status = {}
        self.tx_status_lock = threading.Lock()
        self.tx_timeout_seconds = 600  # 10 minutes

        # Start background worker for gateway submissions
        worker = threading.Thread(target=self._tx_worker, daemon=True)
        worker.start()

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

    def _start_block_confirmation_listener(self):
        """Background listener: receive block_confirmation from RPC server (blockchain)."""
        def listen_loop():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('0.0.0.0', BLOCK_CONFIRMATION_PORT))
                sock.listen(5)
                sock.settimeout(1.0)
                server_logger.info("block_confirmation listener on port %s", BLOCK_CONFIRMATION_PORT)
                self.Print("📡 Block confirmation listener on port %s" % BLOCK_CONFIRMATION_PORT, 20)
                while self.is_running:
                    try:
                        client, addr = sock.accept()
                        client.settimeout(5)
                        data = b''
                        while b'\n' not in data and len(data) < 65536:
                            chunk = client.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                        client.close()
                        if data:
                            line = data.decode('utf-8', errors='ignore').strip()
                            if line:
                                msg = json.loads(line)
                                if msg.get('type') == 'block_confirmation':
                                    server_logger.info(
                                        "block_confirmation block_index=%s block_hash=%s miner_id=%s",
                                        msg.get('block_index'), msg.get('block_hash', '')[:16], msg.get('miner_id')
                                    )
                                    self.Print("✅ Block confirmed: index=%s hash=%s..." % (
                                        msg.get('block_index'), (msg.get('block_hash') or '')[:16]), 20)
                                    # Apply wallet transfers from confirmed transactions
                                    for tx in msg.get('transactions', []):
                                        data = tx.get('data') if isinstance(tx.get('data'), dict) else {}
                                        from_user = data.get('from') or tx.get('sender')
                                        to_user = data.get('to')
                                        amount = data.get('amount') if data.get('amount') is not None else data.get('price')
                                        asset_id = data.get('asset_id')
                                        tx_id = data.get('tx_id')
                                        if from_user and to_user is not None and amount is not None:
                                            try:
                                                amount = float(amount)
                                                ok, res = self.db.transfer(from_user, to_user, amount)
                                                if ok:
                                                    server_logger.info("wallet transfer: %s -> %s amount=%s: %s", from_user, to_user, amount, res)
                                                    self.Print("💰 Saved: %s" % res, 20)
                                                    wa, wb = self.db.get_wallet(from_user), self.db.get_wallet(to_user)
                                                    if wa and wb:
                                                        server_logger.info("balances: %s=%.2f %s=%.2f", from_user, wa['balance'], to_user, wb['balance'])
                                                    if asset_id:
                                                        updated = self.db.update_asset_owner(asset_id, to_user)
                                                        if updated:
                                                            server_logger.info("asset ownership updated: asset_id=%s owner=%s", asset_id, to_user)
                                                        else:
                                                            server_logger.warning("asset ownership update failed: asset_id=%s", asset_id)
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "confirmed", "Transaction confirmed")
                                                else:
                                                    server_logger.warning("wallet transfer failed: %s", res)
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "failed", res)
                                            except (ValueError, TypeError) as e:
                                                server_logger.warning("skip tx (bad amount): %s", e)
                    except socket.timeout:
                        continue
                    except json.JSONDecodeError as e:
                        server_logger.warning("block_confirmation parse error: %s", e)
                    except Exception as e:
                        if self.is_running:
                            server_logger.warning("block_confirmation listener: %s", e)
                sock.close()
            except Exception as e:
                server_logger.error("block_confirmation listener failed: %s", e)
        thread = threading.Thread(target=listen_loop, daemon=True)
        thread.start()

    def _set_tx_status(self, tx_id, status, message=None):
        with self.tx_status_lock:
            info = self.tx_status.get(tx_id)
            if not info:
                self.tx_status[tx_id] = {
                    'status': status,
                    'message': message or '',
                    'created_at': time.time(),
                }
                return
            info['status'] = status
            if message is not None:
                info['message'] = message

    def _get_tx_info(self, tx_id):
        with self.tx_status_lock:
            info = self.tx_status.get(tx_id)
            return dict(info) if info else None

    def _tx_worker(self):
        while True:
            purchase = self.tx_queue.get()
            if not purchase:
                self.tx_queue.task_done()
                continue
            tx_id = purchase.get('tx_id')
            try:
                response = self._submit_purchase_to_gateway(purchase)
                if response and response.get('status') == 'submitted':
                    self._set_tx_status(tx_id, "submitted", response.get('message', 'Submitted to gateway'))
                else:
                    msg = response.get('message') if response else "Gateway did not respond"
                    self._set_tx_status(tx_id, "failed", msg)
            except Exception as e:
                self._set_tx_status(tx_id, "failed", f"Gateway error: {e}")
            finally:
                self.tx_queue.task_done()

    def _submit_purchase_to_gateway(self, purchase):
        payload = {
            'action': 'submit_purchase',
            'body': {
                'tx_id': purchase.get('tx_id'),
                'buyer': purchase.get('buyer'),
                'seller': purchase.get('seller'),
                'asset_id': purchase.get('asset_id'),
                'asset_name': purchase.get('asset_name'),
                'price': purchase.get('amount'),
                'timestamp': purchase.get('timestamp'),
            }
        }
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((GATEWAY_HOST, GATEWAY_PORT))
        raw = json.dumps(payload).encode()
        sock.send(struct.pack('>H', len(raw)) + raw)
        response = self._recv_gateway_json(sock)
        sock.close()
        return response

    def _recv_gateway_json(self, sock, max_size=65536):
        len_buf = sock.recv(2)
        if len(len_buf) < 2:
            return None
        size = struct.unpack('>H', len_buf)[0]
        if size > max_size:
            return None
        data = b''
        while len(data) < size:
            chunk = sock.recv(min(size - len(data), 4096))
            if not chunk:
                return None
            data += chunk
        try:
            return json.loads(data.decode())
        except Exception:
            return None
    
    def start(self):
        """Start the server"""
        self.Print(f"🚀 Server starting on {self.host}:{self.port}...", 20)
        server_logger.info("server starting on %s:%s", self.host, self.port)
        
        try:
            self.is_running = True
            
            # Start broadcast listener thread
            self._start_broadcast_listener()
            # Start block confirmation listener (RPC -> server)
            self._start_block_confirmation_listener()
            
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
            session = ClientSession(sock, addr, self.logging_level, server=self)
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
                        log_msg = msg_str
                        if isinstance(msg_str, str) and msg_str.startswith("UPLOAD_CHUNK|"):
                            parts = msg_str.split("|", 4)
                            if len(parts) >= 4:
                                log_msg = f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}|<chunk>"
                        elif isinstance(msg_str, str) and msg_str.startswith("UPLOAD_INIT|"):
                            log_msg = "UPLOAD_INIT|<payload>"
                        self.Print(f"📩 Received from {addr[0]}:{addr[1]}: {log_msg}", 20)
                        
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
                if session:
                    for upload_id in list(session.upload_sessions.keys()):
                        session._cleanup_upload(upload_id)
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
