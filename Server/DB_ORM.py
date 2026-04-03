"""
Marketplace Database - User Authentication & Items Storage
SQLite database for users and marketplace items with email verification
"""

import sqlite3
import hashlib
import random
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

# Hardcoded pepper (secret)
PEPPER = "aurex_marketplace_2026_secret"

# Database path in DB folder
DB_FOLDER = Path(__file__).parent.parent / "DB"
DB_FOLDER.mkdir(exist_ok=True)
DB_PATH = str(DB_FOLDER / "marketplace.db")

_EMAIL_SENDER = "aurex.main.service@gmail.com"
_EMAIL_APP_PASSWORD = "sshb anri wzom zybg"


def send_reset_email(recipient: str, otp: str) -> bool:
    """Send a password-reset OTP to *recipient* via Gmail SMTP SSL."""
    import datetime as _dt
    expiry = _dt.datetime.now() + _dt.timedelta(minutes=5)

    em = EmailMessage()
    em["From"] = _EMAIL_SENDER
    em["To"] = recipient
    em["Subject"] = "Your Aurex password reset code"
    em.set_content(
        f"Your Code is: {otp}. "
        f"Available until {expiry.strftime('%d/%m/%Y %H:%M:%S')}."
    )

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(_EMAIL_SENDER, _EMAIL_APP_PASSWORD)
            smtp.sendmail(_EMAIL_SENDER, recipient, em.as_string())
        print(f"[email] Reset code sent to {recipient}")
        return True
    except Exception as exc:
        print(f"[email] Failed to send to {recipient}: {exc}")
        return False


def convert_drive_url(drive_url):
    """
    Normalize Google Drive links to a direct view URL the Flutter client can load.

    Handles /file/d/{id}/, open?id=, and already-normalized uc?export=view&id= links.
    Physical folder path (uploads/{username}/…) is not part of the URL; the file id
    is authoritative once the service account uploads under the correct folder.
    """
    if not drive_url or not str(drive_url).strip():
        return drive_url
    s = str(drive_url).strip()

    match = re.search(r'/file/d/([a-zA-Z0-9-_]+)', s)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=view&id={file_id}"

    match_open = re.search(r'[?&]id=([a-zA-Z0-9-_]+)', s)
    if match_open and 'drive.google.com' in s:
        file_id = match_open.group(1)
        return f"https://drive.google.com/uc?export=view&id={file_id}"

    return s


class User:
    """User class with salt + pepper hashing and email verification"""
    
    def __init__(
        self,
        username,
        password,
        email,
        salt=None,
        is_verified=False,
        verification_code=None,
        reset_time=None,
        created_at=None,
        wallet_balance=0.0,
        wallet_updated_at=None,
    ):
        self.username = username
        self.email = email
        self.salt = salt if salt else self._create_salt()
        self.password_hash = self._hash_password(password)
        self.created_at = created_at or datetime.now().isoformat()
        self.is_verified = is_verified
        self.verification_code = verification_code
        self.reset_time = reset_time
        self.wallet_balance = float(wallet_balance)
        self.wallet_updated_at = wallet_updated_at or self.created_at
    
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
        return f"User(username={self.username}, email={self.email}, verified={self.is_verified})"


class MarketplaceDB:
    """Database operations for marketplace"""
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Create tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table with email verification
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_verified INTEGER DEFAULT 0,
                verification_code TEXT,
                reset_time TEXT,
                created_at TEXT NOT NULL,
                wallet_balance REAL DEFAULT 0,
                wallet_updated_at TEXT,
                wallet_public_key TEXT
            )
        ''')

        # Track columns for migration checks
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        # Wallets are now stored in users table (wallet_balance, wallet_updated_at, wallet_public_key)
        if "wallet_balance" not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN wallet_balance REAL DEFAULT 0")
        if "wallet_updated_at" not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN wallet_updated_at TEXT")
        if "wallet_public_key" not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN wallet_public_key TEXT")
        
        # Marketplace items table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marketplace_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_name TEXT NOT NULL,
                description TEXT,
                username TEXT NOT NULL,
                url TEXT NOT NULL,
                file_type TEXT NOT NULL,
                cost REAL NOT NULL,
                asset_hash TEXT,
                owner_public_key TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_listed INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')

        # Ensure columns exist for older DBs
        cursor.execute("PRAGMA table_info(marketplace_items)")
        item_cols = {row[1] for row in cursor.fetchall()}
        if "description" not in item_cols:
            cursor.execute("ALTER TABLE marketplace_items ADD COLUMN description TEXT")
        if "asset_hash" not in item_cols:
            cursor.execute("ALTER TABLE marketplace_items ADD COLUMN asset_hash TEXT")
        if "is_listed" not in item_cols:
            cursor.execute("ALTER TABLE marketplace_items ADD COLUMN is_listed INTEGER NOT NULL DEFAULT 1")
        if "owner_public_key" not in item_cols:
            cursor.execute("ALTER TABLE marketplace_items ADD COLUMN owner_public_key TEXT")

        # Notifications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'system',
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                asset_id TEXT,
                tx_id TEXT,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)')

        # Dedicated wallets table — stores only public identity, never private key.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                username TEXT PRIMARY KEY NOT NULL,
                public_key_hex TEXT NOT NULL,
                key_type TEXT NOT NULL DEFAULT 'ED25519',
                registered_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallets_pubkey ON wallets(public_key_hex)')

        conn.commit()
        conn.close()
    
    def add_user(self, username, password, email):
        """Add new user to database"""
        try:
            user = User(username, password, email)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, salt, created_at, wallet_balance, wallet_updated_at, wallet_public_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user.username,
                user.email,
                user.password_hash,
                user.salt,
                user.created_at,
                100.0,  # Default starting balance
                user.created_at,  # Initial wallet update time
                None,
            ))

            # Wallet is now part of users table - no separate wallets table
            
            conn.commit()
            conn.close()
            return True, "User created successfully"
        except sqlite3.IntegrityError as e:
            if "username" in str(e):
                return False, "Username already exists"
            elif "email" in str(e):
                return False, "Email already exists"
            else:
                return False, str(e)
        except Exception as e:
            return False, f"Error creating user: {str(e)}"
    
    def get_user(self, username):
        """Get user by username"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT username, email, password_hash, salt, is_verified, 
                       verification_code, reset_time, created_at FROM users
                WHERE username = ?
            ''', (username,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user = User(result[0], "", result[1], created_at=result[7])
                user.password_hash = result[2]
                user.salt = result[3]
                user.is_verified = bool(result[4])
                user.verification_code = result[5]
                user.reset_time = result[6]
                return user
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None

    def get_user_public_key(self, username):
        """Get stored public key for a user (if set)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT wallet_public_key FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row[0]
            return None
        except Exception as e:
            print(f"Error getting user public key: {e}")
            return None

    def set_user_public_key(self, username, public_key, force_update=False):
        """Set public key for a user.

        If no key is stored yet, stores it.
        If a matching key is stored, returns True.
        If a different key is stored:
          - force_update=False (default): returns False (security block).
          - force_update=True: updates the stored key (caller must have already
            verified the new key's signature before setting this flag).
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT wallet_public_key FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            existing = row[0] if row else None
            if existing and existing == public_key:
                conn.close()
                return True
            if existing and not force_update:
                conn.close()
                return False
            cursor.execute(
                'UPDATE users SET wallet_public_key = ? WHERE username = ?',
                (public_key, username)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error setting user public key: {e}")
            return False
    
    def set_user_public_key_force(self, username, public_key):
        """Unconditionally overwrite the stored public key (for key regeneration)."""
        return self.set_user_public_key(username, public_key, force_update=True)

    def register_wallet(self, username: str, public_key_b64: str, key_type: str = "ED25519") -> bool:
        """Register or update a wallet entry in the dedicated wallets table.

        Stores only the public key — private key is never accepted or stored.
        Returns True on success, False on error.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                '''
                INSERT INTO wallets (username, public_key_hex, key_type, registered_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    public_key_hex = excluded.public_key_hex,
                    key_type = excluded.key_type
                ''',
                (username, public_key_b64, key_type, now),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error registering wallet: {e}")
            return False

    def get_wallet_pubkey(self, username: str) -> str | None:
        """Return the public key for a username from the wallets table, or None."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT public_key_hex FROM wallets WHERE username = ?', (username,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            print(f"Error getting wallet pubkey: {e}")
            return None

    def get_user_by_email(self, email):
        """Get user by email"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT username, email, password_hash, salt, is_verified,
                       verification_code, reset_time, created_at FROM users
                WHERE email = ?
            ''', (email,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user = User(result[0], "", result[1], created_at=result[7])
                user.password_hash = result[2]
                user.salt = result[3]
                user.is_verified = bool(result[4])
                user.verification_code = result[5]
                user.reset_time = result[6]
                return user
            return None
        except Exception as e:
            print(f"Error getting user by email: {e}")
            return None
    
    def verify_user(self, username, password):
        """Verify user credentials"""
        user = self.get_user(username)
        if user and user.verify_password(password):
            return True
        return False

    def get_wallet(self, username):
        """Get wallet balance for user from users table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT wallet_balance, wallet_updated_at FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {'balance': row[0], 'updated_at': row[1] or datetime.now().isoformat()}
            return None
        except Exception as e:
            print(f"Error getting wallet: {e}")
            return None

    def ensure_wallet(self, username, initial_balance=100):
        """Ensure a user exists and has wallet balance set. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT wallet_balance FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False
            # If wallet_balance is NULL, set it to initial_balance
            if row[0] is None:
                now = datetime.now().isoformat()
                cursor.execute(
                    'UPDATE users SET wallet_balance = ?, wallet_updated_at = ? WHERE username = ?',
                    (float(initial_balance), now, username)
                )
                conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error ensuring wallet: {e}")
            return False

    def update_balance(self, username, new_balance):
        """Set wallet balance in users table. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET wallet_balance = ?, wallet_updated_at = ? WHERE username = ?',
                (float(new_balance), datetime.now().isoformat(), username)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating balance: {e}")
            return False

    def transfer(self, from_user, to_user, amount):
        """Transfer amount between user wallets. Returns (success, message)."""
        if amount <= 0:
            return False, "Amount must be positive"
        try:
            conn = sqlite3.connect(self.db_path)
            conn.isolation_level = None
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute('SELECT wallet_balance FROM users WHERE username = ?', (from_user,))
            row_from = cursor.fetchone()
            cursor.execute('SELECT wallet_balance FROM users WHERE username = ?', (to_user,))
            row_to = cursor.fetchone()
            if not row_from:
                cursor.execute("ROLLBACK")
                conn.close()
                return False, f"User not found: {from_user}"
            if not row_to:
                cursor.execute("ROLLBACK")
                conn.close()
                return False, f"User not found: {to_user}"
            bal_from = row_from[0]
            bal_to = row_to[0]
            if bal_from < amount:
                cursor.execute("ROLLBACK")
                conn.close()
                return False, f"Insufficient balance: {from_user} has {bal_from}"
            now = datetime.now().isoformat()
            cursor.execute(
                'UPDATE users SET wallet_balance = ?, wallet_updated_at = ? WHERE username = ?',
                (bal_from - amount, now, from_user)
            )
            cursor.execute(
                'UPDATE users SET wallet_balance = ?, wallet_updated_at = ? WHERE username = ?',
                (bal_to + amount, now, to_user)
            )
            cursor.execute("COMMIT")
            conn.close()
            return True, f"Transferred {amount} from {from_user} to {to_user}"
        except Exception as e:
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            return False, str(e)

    def seed_alice_bob(self):
        """Create users alice and bob and their wallets (alice 100 coins, bob 0). Idempotent."""
        for username, password, email, balance in [
            ('alice', 'alice123', 'alice@test.com', 100.0),
            ('bob', 'bob123', 'bob@test.com', 0.0),
        ]:
            if self.get_user(username) is None:
                ok, msg = self.add_user(username, password, email)
                print(f"  User {username}: {msg}")
            else:
                print(f"  User {username}: already exists")
            self.ensure_wallet(username, balance)
            w = self.get_wallet(username)
            print(f"  Wallet {username}: balance={w['balance'] if w else 'N/A'}")
        print("  Done: alice and bob ready (alice 100 coins, bob 0).")
    
    def update_user(self, username, user):
        """Update user information (verification status, codes, password)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users SET 
                    password_hash = ?,
                    is_verified = ?,
                    verification_code = ?,
                    reset_time = ?
                WHERE username = ?
            ''', (user.password_hash, int(user.is_verified), user.verification_code,
                  user.reset_time, user.username))
            
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                print(f"Warning: update_user matched no rows for username='{user.username}'")
                return False
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating user: {e}")
            return False
    
    def add_marketplace_item(self, asset_name, username, url, file_type, cost, description="", asset_hash=None, owner_public_key=None):
        """Add item to marketplace"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            direct_url = convert_drive_url(url)

            cursor.execute('''
                INSERT INTO marketplace_items (
                    asset_name, description, username, url, file_type, cost, asset_hash, owner_public_key, timestamp, created_at, is_listed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_name,
                description,
                username,
                direct_url,
                file_type,
                cost,
                asset_hash,
                owner_public_key,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                1,
            ))
            
            item_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return True, "Item added successfully", item_id
        except Exception as e:
            return False, f"Error adding item: {str(e)}", None
    
    def get_all_items(self):
        """Get all marketplace items"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                FROM marketplace_items
                WHERE is_listed = 1
                ORDER BY created_at DESC
            ''')
            
            results = cursor.fetchall()
            conn.close()
            
            items = []
            for row in results:
                items.append({
                    'id': row[0],
                    'asset_name': row[1],
                    'description': row[2],
                    'username': row[3],
                    'url': row[4],
                    'file_type': row[5],
                    'cost': row[6],
                    'asset_hash': row[7],
                    'timestamp': row[8],
                    'created_at': row[9],
                    'is_listed': row[10],
                })
            return items
        except Exception as e:
            print(f"Error getting items: {e}")
            return []
    
    def get_latest_items(self, limit=12):
        """Get latest marketplace items ordered by created_at DESC (used by GET_ITEMS_PAGINATED)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                FROM marketplace_items
                WHERE is_listed = 1
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [
                {'id': r[0], 'asset_name': r[1], 'description': r[2], 'username': r[3],
                 'url': r[4], 'file_type': r[5], 'cost': r[6], 'asset_hash': r[7],
                 'timestamp': r[8], 'created_at': r[9], 'is_listed': r[10]}
                for r in rows
            ]
        except Exception as e:
            print(f"Error in get_latest_items: {e}")
            return []

    def get_items_before_timestamp(self, last_timestamp, limit=12):
        """Get marketplace items created before last_timestamp (cursor-based pagination)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                FROM marketplace_items
                WHERE is_listed = 1 AND created_at < ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (last_timestamp, limit))
            rows = cursor.fetchall()
            conn.close()
            return [
                {'id': r[0], 'asset_name': r[1], 'description': r[2], 'username': r[3],
                 'url': r[4], 'file_type': r[5], 'cost': r[6], 'asset_hash': r[7],
                 'timestamp': r[8], 'created_at': r[9], 'is_listed': r[10]}
                for r in rows
            ]
        except Exception as e:
            print(f"Error in get_items_before_timestamp: {e}")
            return []

    def get_item_by_id(self, item_id):
        """Get marketplace item by ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                FROM marketplace_items WHERE id = ?
            ''', (item_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    'id': result[0],
                    'asset_name': result[1],
                    'description': result[2],
                    'username': result[3],
                    'url': result[4],
                    'file_type': result[5],
                    'cost': result[6],
                    'asset_hash': result[7],
                    'timestamp': result[8],
                    'created_at': result[9],
                    'is_listed': result[10],
                }
            return None
        except Exception as e:
            print(f"Error getting item: {e}")
            return None    

    def get_item_by_hash(self, asset_hash):
        """Get marketplace item by asset hash"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                FROM marketplace_items WHERE asset_hash = ?
            ''', (asset_hash,))
            result = cursor.fetchone()
            conn.close()
            if result:
                return {
                    'id': result[0],
                    'asset_name': result[1],
                    'description': result[2],
                    'username': result[3],
                    'url': result[4],
                    'file_type': result[5],
                    'cost': result[6],
                    'asset_hash': result[7],
                    'timestamp': result[8],
                    'created_at': result[9],
                    'is_listed': result[10],
                }
            return None
        except Exception as e:
            print(f"Error getting item by hash: {e}")
            return None
    def get_items_paginated(self, limit=10, last_timestamp=None):
        """Get paginated marketplace items (lazy scrolling)
        
        Args:
            limit: Number of items to return
            last_timestamp: Timestamp of last item (for pagination)
        
        Returns:
            List of items ordered by creation time (newest first)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if last_timestamp:
                # Get items older than last_timestamp
                cursor.execute('''
                    SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                    FROM marketplace_items
                    WHERE created_at < ? AND is_listed = 1
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (last_timestamp, limit))
            else:
                # Get newest items
                cursor.execute('''
                    SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                    FROM marketplace_items
                    WHERE is_listed = 1
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))
            
            results = cursor.fetchall()
            conn.close()
            
            items = []
            for row in results:
                items.append({
                    'id': row[0],
                    'asset_name': row[1],
                    'description': row[2],
                    'username': row[3],
                    'url': row[4],
                    'file_type': row[5],
                    'cost': row[6],
                    'asset_hash': row[7],
                    'timestamp': row[8],
                    'created_at': row[9],
                    'is_listed': row[10],
                })
            return items
        except Exception as e:
            print(f"Error getting paginated items: {e}")
            return []

    def get_latest_items(self, limit=10):
        """Get the latest marketplace items (for initial load)"""
        return self.get_items_paginated(limit=limit, last_timestamp=None)

    def get_items_before_timestamp(self, timestamp, limit=10):
        """Get items before a specific timestamp (for pagination)"""
        return self.get_items_paginated(limit=limit, last_timestamp=timestamp)

    def get_items_by_username(self, username):
        """Get marketplace items uploaded by a specific user (for GET_ITEMS / asset list)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, asset_hash, timestamp, created_at, is_listed
                FROM marketplace_items
                WHERE username = ?
                ORDER BY created_at DESC
            ''', (username,))
            results = cursor.fetchall()
            conn.close()
            return [
                {'id': row[0], 'asset_name': row[1], 'description': row[2], 'username': row[3], 'url': row[4],
                 'file_type': row[5], 'cost': row[6], 'asset_hash': row[7], 'timestamp': row[8], 'created_at': row[9],
                 'is_listed': row[10]}
                for row in results
            ]
        except Exception as e:
            print(f"Error getting items by username: {e}")
            return []

    def set_item_listed(self, asset_id, is_listed):
        """Update listing status for an item. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE marketplace_items SET is_listed = ? WHERE id = ?',
                (1 if is_listed else 0, asset_id)
            )
            conn.commit()
            updated = cursor.rowcount > 0
            conn.close()
            return updated
        except Exception as e:
            print(f"Error updating listing status: {e}")
            return False

    def update_item_listing(self, asset_id, is_listed, new_cost=None):
        """Update listing status and optionally price. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            if new_cost is None:
                if is_listed:
                    cursor.execute(
                        'UPDATE marketplace_items SET is_listed = ?, timestamp = ?, created_at = ? WHERE id = ?',
                        (1, now, now, asset_id)
                    )
                else:
                    cursor.execute(
                        'UPDATE marketplace_items SET is_listed = ? WHERE id = ?',
                        (0, asset_id)
                    )
            else:
                if is_listed:
                    cursor.execute(
                        'UPDATE marketplace_items SET is_listed = ?, cost = ?, timestamp = ?, created_at = ? WHERE id = ?',
                        (1, float(new_cost), now, now, asset_id)
                    )
                else:
                    cursor.execute(
                        'UPDATE marketplace_items SET is_listed = ?, cost = ? WHERE id = ?',
                        (0, float(new_cost), asset_id)
                    )
            conn.commit()
            updated = cursor.rowcount > 0
            conn.close()
            return updated
        except Exception as e:
            print(f"Error updating item listing: {e}")
            return False

    def update_asset_owner(self, asset_id, new_owner):
        """Update marketplace item owner by asset id. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE marketplace_items SET username = ? WHERE id = ?',
                (new_owner, asset_id)
            )
            conn.commit()
            updated = cursor.rowcount > 0
            conn.close()
            return updated
        except Exception as e:
            print(f"Error updating asset owner: {e}")
            return False

    def update_asset_owner_by_hash(self, asset_hash, new_owner):
        """Update marketplace item owner by asset hash. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE marketplace_items SET username = ? WHERE asset_hash = ?',
                (new_owner, asset_hash)
            )
            conn.commit()
            updated = cursor.rowcount > 0
            conn.close()
            return updated
        except Exception as e:
            print(f"Error updating asset owner by hash: {e}")
            return False

    def create_notification(self, username, title, body, notif_type="system", asset_id=None, tx_id=None):
        """Create a notification for a user. Returns notification dict on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            created_at = datetime.now().isoformat()
            cursor.execute(
                '''INSERT INTO notifications (username, title, body, type, is_read, created_at, asset_id, tx_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (username, title, body, notif_type, 0, created_at, asset_id, tx_id)
            )
            notif_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return {
                'id': notif_id,
                'username': username,
                'title': title,
                'body': body,
                'type': notif_type,
                'is_read': 0,
                'created_at': created_at,
                'asset_id': asset_id,
                'tx_id': tx_id,
            }
        except Exception as e:
            print(f"Error creating notification: {e}")
            return None

    def get_notifications(self, username, limit=50):
        """Get notifications for a user (newest first)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT id, username, title, body, type, is_read, created_at, asset_id, tx_id
                   FROM notifications
                   WHERE username = ?
                   ORDER BY created_at DESC
                   LIMIT ?''',
                (username, limit)
            )
            rows = cursor.fetchall()
            conn.close()
            return [
                {
                    'id': row[0],
                    'username': row[1],
                    'title': row[2],
                    'body': row[3],
                    'type': row[4],
                    'is_read': row[5],
                    'created_at': row[6],
                    'asset_id': row[7],
                    'tx_id': row[8],
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error getting notifications: {e}")
            return []

    def get_unread_notifications_count(self, username):
        """Get unread notification count for user."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT COUNT(1) FROM notifications WHERE username = ? AND is_read = 0',
                (username,)
            )
            row = cursor.fetchone()
            conn.close()
            return int(row[0]) if row else 0
        except Exception as e:
            print(f"Error getting unread notification count: {e}")
            return 0

    def mark_all_notifications_read(self, username):
        """Mark all notifications as read for a user."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE notifications SET is_read = 1 WHERE username = ? AND is_read = 0',
                (username,)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error marking notifications read: {e}")
            return False

    # ---- Device token management (push notifications) ----
    def upsert_device_token(self, username, token, platform="unknown"):
        """Insert or update a device token for push notifications."""
        try:
            if not username or not token:
                return False
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute('SELECT id FROM device_tokens WHERE token = ?', (token,))
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    'UPDATE device_tokens SET username = ?, platform = ?, updated_at = ? WHERE token = ?',
                    (username, platform, now, token),
                )
            else:
                cursor.execute(
                    'INSERT INTO device_tokens (username, token, platform, updated_at) VALUES (?, ?, ?, ?)',
                    (username, token, platform, now),
                )

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error upserting device token: {e}")
            return False

    def get_device_tokens(self, username):
        """Return all device tokens for a user."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT token FROM device_tokens WHERE username = ?',
                (username,),
            )
            rows = cursor.fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception as e:
            print(f"Error getting device tokens: {e}")
            return []

    def delete_device_token(self, token):
        """Remove a device token (e.g. invalidated by FCM)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM device_tokens WHERE token = ?', (token,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting device token: {e}")
            return False
