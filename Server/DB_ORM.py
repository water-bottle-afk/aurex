"""
Marketplace Database - User Authentication & JSON storage
"""

from __future__ import annotations

import json
import hashlib
import pickle
import random
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from SharedResources.logging import Logger

logger = Logger(__file__)

PEPPER = "aurex_marketplace_2026_secret"
DB_FOLDER = Path(__file__).parent.parent / "DB"
DB_FOLDER.mkdir(exist_ok=True)

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
        logger.info(f"[email] Reset code sent to {recipient}")
        return True
    except Exception as exc:
        logger.error(f"[email] Failed to send to {recipient}: {exc}")
        return False


class User:
    """User model with password hash + verification fields + hex public key."""

    def __init__(
        self,
        username,
        password,
        email,
        salt=None,
        public_key="",
        verification_code=None,
        reset_time=None,
        password_hash=None,
    ):
        self.username = str(username or "").strip()
        self.email = str(email or "").strip().lower()
        self.salt = str(salt) if salt else self._create_salt()
        self.password_hash = str(password_hash) if password_hash else self._hash_password(password or "")
        self.verification_code = verification_code
        self.reset_time = reset_time
        self.public_key = str(public_key or "")

    def _create_salt(self):
        return str(random.randint(1000000, 9999999))

    def _hash_password(self, password):
        combined = PEPPER + str(password) + self.salt
        return hashlib.sha256(combined.encode()).hexdigest()

    def verify_password(self, password):
        return self.password_hash == self._hash_password(password)

    def set_verification_code(self, code):
        self.verification_code = code

    def set_reset_time(self, value):
        self.reset_time = value

    def is_code_match_and_available(self, current_time, code_to_check):
        if self.verification_code == code_to_check and self.reset_time:
            return current_time < datetime.fromisoformat(self.reset_time)
        return False

    def set_password(self, new_password):
        self.password_hash = self._hash_password(new_password)

    def set_public_key(self, public_key):
        self.public_key = str(public_key or "")

    def to_dict(self):
        return {
            "username": self.username,
            "email": self.email,
            "salt": self.salt,
            "password_hash": self.password_hash,
            "public_key": self.public_key,
            "verification_code": self.verification_code,
            "reset_time": self.reset_time,
        }

    @classmethod
    def from_dict(cls, raw):
        return cls(
            username=raw.get("username", ""),
            password="",
            email=raw.get("email", ""),
            salt=raw.get("salt"),
            public_key=raw.get("public_key", ""),
            verification_code=raw.get("verification_code"),
            reset_time=raw.get("reset_time"),
            password_hash=raw.get("password_hash", ""),
        )

    def __repr__(self):
        key_tail = self.public_key[-10:] if self.public_key else "none"
        return (
            "User("  # intentionally explicit for JSON re-hydration debug
            f"username='{self.username}', "
            f"email='{self.email}', "
            f"salt='{self.salt}', "
            f"password_hash='{self.password_hash[:12]}...', "
            f"public_key_tail='{key_tail}', "
            f"verification_code={'set' if self.verification_code else 'none'}, "
            f"reset_time='{self.reset_time}'"
            ")"
        )


class ORM:
    """JSON-based ORM for users: DB/users.json -> {username: user_dict}"""

    def __init__(self, users_json_path=None, users_pickle_path=None):
        self.users_json_path = Path(users_json_path) if users_json_path else (DB_FOLDER / "users.json")
        self.users_pickle_path = Path(users_pickle_path) if users_pickle_path else (DB_FOLDER / "users.pickle")
        self.users_json_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.users_json_path.exists():
            self.users_json_path.write_text("{}", encoding="utf-8")
        self._migrate_users_pickle_once()

    def _migrate_users_pickle_once(self):
        if self.users_json_path.exists():
            try:
                existing = json.loads(self.users_json_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing:
                    return
            except Exception:
                pass
        if not self.users_pickle_path.exists():
            return
        try:
            with self.users_pickle_path.open("rb") as f:
                old_data = pickle.load(f)
            users_map = {}
            if isinstance(old_data, dict):
                for uname, raw in old_data.items():
                    if isinstance(raw, User):
                        user = raw
                    elif isinstance(raw, dict):
                        user = User.from_dict(raw)
                    else:
                        # best effort fallback for legacy objects
                        user = User(
                            username=getattr(raw, "username", uname),
                            password="",
                            email=getattr(raw, "email", ""),
                            salt=getattr(raw, "salt", None),
                            public_key=getattr(raw, "public_key", ""),
                            verification_code=getattr(raw, "verification_code", None),
                            reset_time=getattr(raw, "reset_time", None),
                            password_hash=getattr(raw, "password_hash", ""),
                        )
                    users_map[str(user.username)] = user.to_dict()
            tmp_path = self.users_json_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(users_map, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self.users_json_path)
            logger.info(f"Migrated users.pickle -> users.json ({len(users_map)} users)")
        except Exception as exc:
            logger.error(f"Failed migrating users pickle: {exc}")

    def _load_users(self):
        try:
            raw = json.loads(self.users_json_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            return {uname: User.from_dict(data) for uname, data in raw.items() if isinstance(data, dict)}
        except Exception as e:
            logger.error(f"Error loading users json: {e}")
            return {}

    def _save_users(self, users):
        payload = {}
        for uname, user in users.items():
            if isinstance(user, User):
                payload[str(uname)] = user.to_dict()
            elif isinstance(user, dict):
                payload[str(uname)] = user
        self.users_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_user(self, username, password, email):
        username = (username or "").strip()
        email = (email or "").strip().lower()
        password = password or ""
        if not username or not email or not password:
            return False, "Missing required fields"

        users = self._load_users()
        if username in users:
            return False, "Username already exists"
        if any((u.email or "").lower() == email for u in users.values()):
            return False, "Email already exists"

        users[username] = User(username, password, email)
        self._save_users(users)
        return True, "User created successfully"

    def get_user(self, username):
        username = (username or "").strip()
        if not username:
            return None
        users = self._load_users()
        return users.get(username)
