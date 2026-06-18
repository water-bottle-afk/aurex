"""
DB_ORM.py — all database access for the Aurex marketplace.

Uses plain JSON files (no SQL, no pickle) with an RLock for thread safety.
Three tables: users.json, marketplace_items.json, notifications.json.
Everything the server needs to persist goes through the ORM class.

marketplace_items.json schema: { asset_id -> asset_dict }
users.json schema:             { username -> user_dict }
"""
from __future__ import annotations

__author__ = "Nadav"

import hashlib
import json
import random
import smtplib
import ssl
import threading
from datetime import datetime, timedelta
from pathlib import Path

from SharedResources.logging import Logger
from SharedResources.classes import (
    MarketplaceItem,
    migrate_asset_status,
    ASSET_STATUS_PENDING,
    ASSET_STATUS_FOR_SALE,
    ASSET_STATUS_UNLISTED,
    ASSET_STATUS_SOLD,
    ASSET_STATUS_PENDING_DELETION,
    ASSET_STATUS_DELETED,
)

logger = Logger(__file__)

DB_FOLDER = Path(__file__).parent.parent / "DB"
DB_FOLDER.mkdir(exist_ok=True)

def load_pepper() -> str:
    p = DB_FOLDER / "pepper.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "aurex_marketplace_2026_secret"

PEPPER = load_pepper()

EMAIL_SENDER = "aurex.main.service@gmail.com"
EMAIL_APP_PASSWORD = "sshb anri wzom zybg"


def send_reset_email(recipient: str, otp: str) -> bool:
    """Send a password-reset OTP to *recipient* via Gmail SMTP SSL."""
    import datetime as dt

    expiry = dt.datetime.now() + dt.timedelta(minutes=5)
    em = __import__("email.message", fromlist=["EmailMessage"]).EmailMessage()
    em["From"] = EMAIL_SENDER
    em["To"] = recipient
    em["Subject"] = "Your Aurex password reset code"
    em.set_content(
        f"Your Code is: {otp}. "
        f"Available until {expiry.strftime('%d/%m/%Y %H:%M:%S')}."
    )
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.sendmail(EMAIL_SENDER, recipient, em.as_string())
        logger.info(f"[email] Reset code sent to {recipient}")
        return True
    except Exception as exc:
        logger.error(f"[email] Failed to send to {recipient}: {exc}")
        return False


# ── Domain models ─────────────────────────────────────────────────────────────

class User:
    """User model with salted+peppered password hash.

    Soft-delete sets user_status='DELETED' and clears sensitive fields
    (email, password_hash, salt, verification_code, reset_time) while
    preserving username and public_key so historical blockchain records
    remain linkable.
    """

    def __init__(self, username, password, email, salt=None, public_key="",
                 verification_code=None, reset_time=None, password_hash=None,
                 user_status="ACTIVE"):
        self.username = str(username or "").strip()
        self.email = str(email or "").strip().lower()
        self.salt = str(salt) if salt else self.create_salt()
        self.password_hash = str(password_hash) if password_hash else self.hash_password(password or "")
        self.verification_code = verification_code
        self.reset_time = reset_time
        self.public_key = str(public_key or "")
        self.user_status = str(user_status or "ACTIVE")

    def create_salt(self):
        return str(random.randint(1000000, 9999999))

    def hash_password(self, password):
        return hashlib.sha256((PEPPER + str(password) + self.salt).encode()).hexdigest()

    def verify_password(self, password):
        if self.is_deleted():
            return False
        return self.password_hash == self.hash_password(password)

    def is_deleted(self) -> bool:
        return self.user_status == "DELETED"

    def set_verification_code(self, code):
        self.verification_code = code

    def set_reset_time(self, value):
        self.reset_time = value

    def is_code_match_and_available(self, current_time, code_to_check):
        if self.verification_code == code_to_check and self.reset_time:
            return current_time < datetime.fromisoformat(self.reset_time)
        return False

    def set_password(self, new_password):
        self.password_hash = self.hash_password(new_password)

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
            "user_status": self.user_status,
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
            user_status=raw.get("user_status", "ACTIVE"),
        )

    def __repr__(self):
        return (
            f"User(username='{self.username}', status='{self.user_status}', "
            f"public_key_tail='{self.public_key[-10:] if self.public_key else 'none'}')"
        )


# ── Unified ORM ───────────────────────────────────────────────────────────────

class ORM:
    """
    Unified JSON ORM for users, marketplace assets, and notifications.
    All DB I/O goes through this class — no direct file access from the server.

    marketplace_items.json top-level key is asset_id (O(1) lookup, no nested lists).
    """

    def __init__(self, users_json_path=None, marketplace_json_path=None, notifications_json_path=None):
        self.users_json_path = (
            Path(users_json_path) if users_json_path else DB_FOLDER / "users.json"
        )
        self.marketplace_json_path = (
            Path(marketplace_json_path) if marketplace_json_path else DB_FOLDER / "marketplace_items.json"
        )
        self.notifications_json_path = (
            Path(notifications_json_path) if notifications_json_path else DB_FOLDER / "notifications.json"
        )
        for path in (self.users_json_path, self.marketplace_json_path, self.notifications_json_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("{}", encoding="utf-8")
        self.lock = threading.RLock()

    # ── Users ─────────────────────────────────────────────────────────────────

    def load_users(self) -> dict[str, User]:
        try:
            raw = json.loads(self.users_json_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            return {k: User.from_dict(v) for k, v in raw.items() if isinstance(v, dict)}
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            return {}

    def save_users(self, users: dict):
        payload = {
            str(k): (v.to_dict() if isinstance(v, User) else v)
            for k, v in users.items()
        }
        self.users_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_user(self, username: str, password: str, email: str):
        """Register a new user. Checks for duplicate username and email before writing."""
        username = (username or "").strip()
        email = (email or "").strip().lower()
        if not username or not email or not password:
            return False, "Missing required fields"
        with self.lock:
            users = self.load_users()
            # Check active users only; soft-deleted username slots stay reserved
            if username in users:
                return False, "Username already exists"
            if any(u.email == email and not u.is_deleted() for u in users.values()):
                return False, "Email already exists"
            users[username] = User(username, password, email)
            self.save_users(users)
        return True, "User created successfully"

    def get_user(self, username: str):
        return self.load_users().get((username or "").strip())

    def save_user(self, user: User):
        with self.lock:
            users = self.load_users()
            users[user.username] = user
            self.save_users(users)

    def get_user_by_email(self, email: str):
        email = (email or "").strip().lower()
        for user in self.load_users().values():
            if user.email == email and not user.is_deleted():
                return user
        return None

    def get_user_by_public_key(self, public_key: str):
        public_key = (public_key or "").strip()
        if not public_key:
            return None
        for user in self.load_users().values():
            if user.public_key == public_key:
                return user
        return None

    def resolve_username(self, public_key: str) -> str:
        """Return username for a public key. Handles soft-deleted accounts gracefully."""
        user = self.get_user_by_public_key(public_key)
        if user is None:
            return ""
        if user.is_deleted():
            return "Deleted User (Historical)"
        return user.username

    def is_public_key_taken(self, public_key: str, exclude_username: str = "") -> bool:
        """Return True if this public key is already registered to a DIFFERENT active user."""
        public_key = (public_key or "").strip()
        if not public_key:
            return False
        exclude = (exclude_username or "").strip()
        for user in self.load_users().values():
            if user.public_key == public_key and user.username != exclude and not user.is_deleted():
                return True
        return False

    def set_user_public_key(self, username: str, public_key: str) -> bool:
        user = self.get_user(username)
        if not user or user.is_deleted():
            return False
        user.set_public_key(public_key)
        self.save_user(user)
        return True

    def issue_reset_code(self, email: str, minutes_valid: int = 5):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found", None
        code = str(random.randint(100000, 999999))
        user.set_verification_code(code)
        user.set_reset_time((datetime.now() + timedelta(minutes=minutes_valid)).isoformat())
        self.save_user(user)
        return True, "Code issued", code

    def verify_reset_code(self, email: str, code: str):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found", None
        if user.verification_code != code:
            return False, "Invalid verification code", None
        if not user.reset_time or datetime.now() >= datetime.fromisoformat(user.reset_time):
            return False, "Code expired", None
        return True, "Code verified", user

    def update_password_by_email(self, email: str, new_password: str):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found"
        user.set_password(new_password)
        self.save_user(user)
        return True, "Password updated"

    def soft_delete_user(self, username: str) -> bool:
        """Soft-delete: erase credentials, set user_status=DELETED, keep public_key."""
        username = (username or "").strip()
        if not username:
            return False
        with self.lock:
            users = self.load_users()
            user = users.get(username)
            if not user:
                return False
            # Erase all sensitive fields
            user.email = ""
            user.password_hash = ""
            user.salt = ""
            user.verification_code = None
            user.reset_time = None
            user.user_status = "DELETED"
            # public_key and username are preserved for historical ledger linkage
            self.save_users(users)
        logger.info(f"[ORM] soft_delete_user: {username} marked DELETED")
        return True

    # Keep the old name as an alias so existing callers don't break during transition
    def delete_user(self, username: str) -> bool:
        return self.soft_delete_user(username)

    # ── Marketplace ───────────────────────────────────────────────────────────

    def load_marketplace(self) -> dict[str, dict]:
        """Load marketplace JSON. Top-level key is asset_id → asset_dict."""
        try:
            raw = json.loads(self.marketplace_json_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            result: dict[str, dict] = {}
            for key, value in raw.items():
                if not isinstance(value, dict):
                    continue
                # Migrate status fields on load
                item_dict = MarketplaceItem.from_dict(value).to_dict()
                aid = item_dict.get("asset_id") or key
                if aid:
                    result[str(aid)] = item_dict
            return result
        except Exception:
            return {}

    def save_marketplace(self, market: dict[str, dict]):
        self.marketplace_json_path.write_text(
            json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_asset(self, username: str, asset: MarketplaceItem) -> bool:
        _ = username  # owner is stored inside asset.owner
        with self.lock:
            market = self.load_marketplace()
            market[asset.asset_id] = asset.to_dict()
            self.save_marketplace(market)
        return True

    def get_all_assets(self) -> list[MarketplaceItem]:
        market = self.load_marketplace()
        assets = [MarketplaceItem.from_dict(d) for d in market.values()]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_all_for_sale_assets(self) -> list[MarketplaceItem]:
        """Return all FOR_SALE assets regardless of owner."""
        market = self.load_marketplace()
        assets = [
            MarketplaceItem.from_dict(d)
            for d in market.values()
            if isinstance(d, dict) and d.get("asset_status") == ASSET_STATUS_FOR_SALE
        ]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_all_for_sale_asset_ids(self) -> list[dict]:
        return [{"id": a.asset_id, "version": a.version} for a in self.get_all_for_sale_assets() if a.asset_id]

    def update_asset_status(self, asset_id: str, status: str,
                            increment_version: bool = False) -> bool:
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return False
        with self.lock:
            market = self.load_marketplace()
            asset_dict = market.get(asset_id)
            if asset_dict is None:
                return False
            asset_dict["asset_status"] = status
            if increment_version:
                asset_dict["version"] = int(asset_dict.get("version", 1)) + 1
            market[asset_id] = asset_dict
            self.save_marketplace(market)
        return True

    def transfer_asset(self, asset_id: str, from_owner: str, to_owner: str) -> bool:
        """Transfer an asset to a new owner after a confirmed blockchain purchase.

        Accepts the transfer if the asset is FOR_SALE (normal case) or
        PENDING_DELETION (purchase beat the account-deletion window — blockchain wins).
        Returns False for any other status (already sold / deleted) to prevent double-buys.
        """
        asset_id = (asset_id or "").strip()
        from_owner = (from_owner or "").strip()
        to_owner = (to_owner or "").strip()
        if not asset_id or not from_owner or not to_owner:
            return False
        with self.lock:
            market = self.load_marketplace()
            asset_dict = market.get(asset_id)
            if asset_dict is None:
                return False
            current_status = str(asset_dict.get("asset_status", ""))
            current_owner = str(asset_dict.get("owner", ""))

            if current_status == ASSET_STATUS_PENDING_DELETION:
                # Blockchain purchase beat the account-deletion — transfer allowed
                pass
            elif current_status == ASSET_STATUS_FOR_SALE and current_owner == from_owner:
                # Normal validated purchase
                pass
            else:
                # Double-buy or wrong state — reject
                return False

            asset_dict["owner"] = to_owner
            asset_dict["asset_status"] = ASSET_STATUS_UNLISTED
            asset_dict["version"] = int(asset_dict.get("version", 1)) + 1
            market[asset_id] = asset_dict
            self.save_marketplace(market)
        return True

    def delete_asset(self, asset_id: str, owner: str) -> bool:
        """Remove an asset entry entirely from the DB."""
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return False
        with self.lock:
            market = self.load_marketplace()
            if asset_id not in market:
                return False
            # Optionally verify owner still matches (soft-deleted owners allowed)
            asset_dict = market[asset_id]
            if owner and str(asset_dict.get("owner", "")) != owner:
                return False
            del market[asset_id]
            self.save_marketplace(market)
        return True

    def get_assets_for_user(self, username: str) -> list[MarketplaceItem]:
        """Return assets owned by user that are NOT FOR_SALE (My Assets view)."""
        username = (username or "").strip()
        if not username:
            return []
        market = self.load_marketplace()
        assets = [
            MarketplaceItem.from_dict(d)
            for d in market.values()
            if isinstance(d, dict)
            and d.get("owner") == username
            and d.get("asset_status") != ASSET_STATUS_FOR_SALE
        ]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_all_assets_for_user_any_status(self, username: str) -> list[MarketplaceItem]:
        """Return all assets owned by user regardless of status."""
        username = (username or "").strip()
        if not username:
            return []
        market = self.load_marketplace()
        assets = [
            MarketplaceItem.from_dict(d)
            for d in market.values()
            if isinstance(d, dict) and d.get("owner") == username
        ]
        return assets

    def set_assets_pending_deletion(self, username: str) -> list[str]:
        """Freeze all user assets in PENDING_DELETION. Returns affected asset_ids.

        Called immediately when a user deletes their account so the marketplace
        grid stops showing those items before the blockchain window closes.
        """
        username = (username or "").strip()
        if not username:
            return []
        affected: list[str] = []
        with self.lock:
            market = self.load_marketplace()
            for aid, d in market.items():
                if not isinstance(d, dict):
                    continue
                if d.get("owner") != username:
                    continue
                if d.get("asset_status") in (ASSET_STATUS_DELETED, ASSET_STATUS_PENDING_DELETION):
                    continue
                d["asset_status"] = ASSET_STATUS_PENDING_DELETION
                affected.append(aid)
            if affected:
                self.save_marketplace(market)
        return affected

    # Keep old name so callers that pre-existed the soft-delete refactor still work
    def delete_user_assets(self, username: str):
        self.set_assets_pending_deletion(username)

    def find_asset_by_id(self, asset_id: str):
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return None
        d = self.load_marketplace().get(asset_id)
        return MarketplaceItem.from_dict(d) if isinstance(d, dict) else None

    # ── Notifications ─────────────────────────────────────────────────────────

    def load_notifications(self) -> dict:
        try:
            data = json.loads(self.notifications_json_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_notifications(self, data: dict):
        self.notifications_json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def queue_notification(self, username: str, msg: str):
        username = str(username or "").strip()
        if not username:
            return
        with self.lock:
            data = self.load_notifications()
            items = data.get(username, [])
            if not isinstance(items, list):
                items = []
            items.append({"msg": str(msg)})
            data[username] = items
            self.save_notifications(data)

    def flush_notifications(self, username: str) -> list[str]:
        """Return and clear all queued notifications for the user."""
        username = str(username or "").strip()
        if not username:
            return []
        with self.lock:
            data = self.load_notifications()
            items = data.get(username, [])
            data[username] = []
            self.save_notifications(data)
        if not isinstance(items, list):
            return []
        return [str(i.get("msg", "")) if isinstance(i, dict) else str(i) for i in items if i]
