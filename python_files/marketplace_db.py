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
    
    def __init__(self, username, password, email, salt=None, is_verified=False, 
                 verification_code=None, reset_time=None):
        self.username = username
        self.email = email
        self.salt = salt if salt else self._create_salt()
        self.password_hash = self._hash_password(password)
        self.created_at = datetime.now().isoformat()
        self.is_verified = is_verified
        self.verification_code = verification_code
        self.reset_time = reset_time
    
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
                created_at TEXT NOT NULL
            )
        ''')
        
        # Marketplace items table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marketplace_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_name TEXT NOT NULL,
                username TEXT NOT NULL,
                url TEXT NOT NULL,
                file_type TEXT NOT NULL,
                cost REAL NOT NULL,
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_user(self, username, password, email):
        """Add new user to database"""
        try:
            user = User(username, password, email)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user.username, user.email, user.password_hash, user.salt, user.created_at))
            
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
                user = User(result[0], "", result[1])
                user.password_hash = result[2]
                user.salt = result[3]
                user.is_verified = bool(result[4])
                user.verification_code = result[5]
                user.reset_time = result[6]
                user.created_at = result[7]
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
                       verification_code, reset_time, created_at FROM users
                WHERE email = ?
            ''', (email,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user = User(result[0], "", result[1])
                user.password_hash = result[2]
                user.salt = result[3]
                user.is_verified = bool(result[4])
                user.verification_code = result[5]
                user.reset_time = result[6]
                user.created_at = result[7]
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
    
    def add_marketplace_item(self, asset_name, username, url, file_type, cost):
        """Add item to marketplace"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Convert Google Drive URL to direct view URL
            direct_url = convert_drive_url(url)
            
            cursor.execute('''
                INSERT INTO marketplace_items (asset_name, username, url, file_type, cost, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (asset_name, username, direct_url, file_type, cost, datetime.now().isoformat(), datetime.now().isoformat()))
            
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
                SELECT id, asset_name, username, url, file_type, cost, timestamp, created_at
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
                    'username': row[2],
                    'url': row[3],
                    'file_type': row[4],
                    'cost': row[5],
                    'timestamp': row[6],
                    'created_at': row[7]
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
                SELECT id, asset_name, username, url, file_type, cost, timestamp, created_at
                FROM marketplace_items WHERE id = ?
            ''', (item_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    'id': result[0],
                    'asset_name': result[1],
                    'username': result[2],
                    'url': result[3],
                    'file_type': result[4],
                    'cost': result[5],
                    'timestamp': result[6],
                    'created_at': result[7]
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
                    SELECT id, asset_name, username, url, file_type, cost, timestamp, created_at
                    FROM marketplace_items
                    WHERE created_at < ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (last_timestamp, limit))
            else:
                # Get newest items
                cursor.execute('''
                    SELECT id, asset_name, username, url, file_type, cost, timestamp, created_at
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
                    'username': row[2],
                    'url': row[3],
                    'file_type': row[4],
                    'cost': row[5],
                    'timestamp': row[6],
                    'created_at': row[7]
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