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

# Email configuration (use environment variables in production)
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "your-email@gmail.com")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "your-app-password")


def convert_drive_url(drive_url):
    """
    Convert Google Drive share link to direct view URL
    Input:  https://drive.google.com/file/d/{ID}/view?usp=sharing
    Output: https://drive.google.com/uc?export=view&id={ID}
    (This URL works in Flutter Image widget)
    """
    match = re.search(r'/file/d/([a-zA-Z0-9-_]+)', drive_url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    return drive_url


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
        
        # Users table with email verification + wallet
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
                wallet_balance REAL NOT NULL DEFAULT 0,
                wallet_updated_at TEXT
            )
        ''')

        # Track columns for migration checks
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        # Ensure wallet columns exist for older DBs
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "wallet_balance" not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN wallet_balance REAL NOT NULL DEFAULT 0")
        if "wallet_updated_at" not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN wallet_updated_at TEXT")
        
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
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')

        # Ensure description column exists for older DBs
        cursor.execute("PRAGMA table_info(marketplace_items)")
        item_cols = {row[1] for row in cursor.fetchall()}
        if "description" not in item_cols:
            cursor.execute("ALTER TABLE marketplace_items ADD COLUMN description TEXT")

        # Normalize empty wallet balances to default
        cursor.execute(
            "UPDATE users SET wallet_balance = 100 WHERE wallet_balance IS NULL OR wallet_balance = ''"
        )
        
        conn.commit()
        conn.close()
    
    def add_user(self, username, password, email):
        """Add new user to database"""
        try:
            user = User(username, password, email)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, salt, created_at, wallet_balance, wallet_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user.username,
                user.email,
                user.password_hash,
                user.salt,
                user.created_at,
                100.0,
                user.created_at,
            ))
            
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
                       verification_code, reset_time, created_at, wallet_balance, wallet_updated_at FROM users
                WHERE username = ?
            ''', (username,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user = User(result[0], "", result[1], created_at=result[7],
                            wallet_balance=result[8], wallet_updated_at=result[9])
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
    
    def get_user_by_email(self, email):
        """Get user by email"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT username, email, password_hash, salt, is_verified,
                       verification_code, reset_time, created_at, wallet_balance, wallet_updated_at FROM users
                WHERE email = ?
            ''', (email,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user = User(result[0], "", result[1], created_at=result[7],
                            wallet_balance=result[8], wallet_updated_at=result[9])
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
            return {'balance': row[0], 'updated_at': row[1]} if row else None
        except Exception as e:
            print(f"Error getting wallet: {e}")
            return None

    def ensure_wallet(self, username, initial_balance=100):
        """Ensure wallet fields are initialized for user. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT wallet_balance FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False
            now = datetime.now().isoformat()
            current_balance = row[0]
            if current_balance in (None, ""):
                current_balance = initial_balance
            cursor.execute(
                'UPDATE users SET wallet_balance = ?, wallet_updated_at = ? WHERE username = ?',
                (float(current_balance), now, username)
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
        """Transfer amount between wallets. Returns (success, message)."""
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
                return False, f"Wallet not found: {from_user}"
            if not row_to:
                cursor.execute("ROLLBACK")
                conn.close()
                return False, f"Wallet not found: {to_user}"
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
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating user: {e}")
            return False
    
    def add_marketplace_item(self, asset_name, username, url, file_type, cost, description=""):
        """Add item to marketplace"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Convert Google Drive URL to direct view URL
            direct_url = convert_drive_url(url)
            
            cursor.execute('''
                INSERT INTO marketplace_items (asset_name, description, username, url, file_type, cost, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_name,
                description,
                username,
                direct_url,
                file_type,
                cost,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ))
            
            conn.commit()
            conn.close()
            return True, "Item added successfully"
        except Exception as e:
            return False, f"Error adding item: {str(e)}"
    
    def get_all_items(self):
        """Get all marketplace items"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, timestamp, created_at
                FROM marketplace_items
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
                    'timestamp': row[7],
                    'created_at': row[8]
                })
            return items
        except Exception as e:
            print(f"Error getting items: {e}")
            return []
    
    def get_item_by_id(self, item_id):
        """Get marketplace item by ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, asset_name, description, username, url, file_type, cost, timestamp, created_at
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
                    'timestamp': result[7],
                    'created_at': result[8]
                }
            return None
        except Exception as e:
            print(f"Error getting item: {e}")
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
                    SELECT id, asset_name, description, username, url, file_type, cost, timestamp, created_at
                    FROM marketplace_items
                    WHERE created_at < ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (last_timestamp, limit))
            else:
                # Get newest items
                cursor.execute('''
                    SELECT id, asset_name, description, username, url, file_type, cost, timestamp, created_at
                    FROM marketplace_items
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
                    'timestamp': row[7],
                    'created_at': row[8]
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
                SELECT id, asset_name, description, username, url, file_type, cost, timestamp, created_at
                FROM marketplace_items
                WHERE username = ?
                ORDER BY created_at DESC
            ''', (username,))
            results = cursor.fetchall()
            conn.close()
            return [
                {'id': row[0], 'asset_name': row[1], 'description': row[2], 'username': row[3], 'url': row[4],
                 'file_type': row[5], 'cost': row[6], 'timestamp': row[7], 'created_at': row[8]}
                for row in results
            ]
        except Exception as e:
            print(f"Error getting items by username: {e}")
            return []

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
