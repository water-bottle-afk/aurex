"""
Aurex Database ORM — unified class for users + marketplace + notifications.
JSON-backed, thread-safe, no pickle.
"""

from __future__ import annotations

import hashlib
import json
import random
import smtplib
import ssl
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from SharedResources.logging import Logger

logger = Logger(__file__)

DB_FOLDER = Path(__file__).parent.parent / "DB"
DB_FOLDER.mkdir(exist_ok=True)

def _load_pepper() -> str:
    p = DB_FOLDER / "pepper.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "aurex_marketplace_2026_secret"

PEPPER = _load_pepper()

_EMAIL_SENDER = "aurex.main.service@gmail.com"
_EMAIL_APP_PASSWORD = "sshb anri wzom zybg"

# Valid asset status values
ASSET_STATUS_PENDING  = "PENDING"
ASSET_STATUS_FOR_SALE = "FOR_SALE"
ASSET_STATUS_UNLISTED = "UNLISTED"
ASSET_STATUS_SOLD     = "SOLD"


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


# ── Domain models ─────────────────────────────────────────────────────────────

class User:
    """User model with salted+peppered password hash."""

    def __init__(self, username, password, email, salt=None, public_key="",
                 verification_code=None, reset_time=None, password_hash=None):
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
        return hashlib.sha256((PEPPER + str(password) + self.salt).encode()).hexdigest()

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
        return (
            f"User(username='{self.username}', email='{self.email}', "
            f"public_key_tail='{self.public_key[-10:] if self.public_key else 'none'}')"
        )


def _migrate_asset_status(raw: dict) -> str:
    """Derive asset_status from old blockchain_status/for_sale fields when upgrading."""
    if "asset_status" in raw:
        return str(raw["asset_status"])
    bc = str(raw.get("blockchain_status", "")).strip().lower()
    fs = bool(raw.get("for_sale", True))
    if bc in ("verified",):
        return ASSET_STATUS_FOR_SALE if fs else ASSET_STATUS_UNLISTED
    return ASSET_STATUS_PENDING


@dataclass
class MarketplaceItem:
    """Marketplace asset stored in DB/marketplace_items.json."""

    asset_id: str
    owner: str
    asset_name: str
    description: str
    file_type: str
    cost: float
    storage_path: str
    created_at: str
    version: int = 1
    asset_status: str = ASSET_STATUS_PENDING
    public_key: str = ""

    def to_dict(self):
        return {
            "asset_id": self.asset_id,
            "owner": self.owner,
            "asset_name": self.asset_name,
            "description": self.description,
            "file_type": self.file_type,
            "cost": self.cost,
            "storage_path": self.storage_path,
            "created_at": self.created_at,
            "version": self.version,
            "asset_status": self.asset_status,
            "public_key": self.public_key,
        }

    @classmethod
    def from_dict(cls, raw):
        return cls(
            asset_id=str(raw.get("asset_id", "")),
            owner=str(raw.get("owner", "")),
            asset_name=str(raw.get("asset_name", "")),
            description=str(raw.get("description", "")),
            file_type=str(raw.get("file_type", "")),
            cost=float(raw.get("cost", 0.0)),
            storage_path=str(raw.get("storage_path", "")),
            created_at=str(raw.get("created_at", "")),
            version=int(raw.get("version", 1)),
            asset_status=_migrate_asset_status(raw),
            public_key=str(raw.get("public_key", "")),
        )

    def __repr__(self):
        return (
            f"MarketplaceItem(asset_id='{self.asset_id}', owner='{self.owner}', "
            f"asset_name='{self.asset_name}', cost={self.cost}, status={self.asset_status})"
        )


# ── Unified ORM ───────────────────────────────────────────────────────────────

class ORM:
    """
    Unified JSON ORM for users, marketplace assets, and notifications.
    All DB I/O goes through this class — no direct file access from the server.
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
        self._lock = threading.RLock()

    # ── Users ─────────────────────────────────────────────────────────────────

    def _load_users(self) -> dict[str, User]:
        try:
            raw = json.loads(self.users_json_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            return {k: User.from_dict(v) for k, v in raw.items() if isinstance(v, dict)}
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            return {}

    def _save_users(self, users: dict):
        payload = {
            str(k): (v.to_dict() if isinstance(v, User) else v)
            for k, v in users.items()
        }
        self.users_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_user(self, username: str, password: str, email: str):
        username = (username or "").strip()
        email = (email or "").strip().lower()
        if not username or not email or not password:
            return False, "Missing required fields"
        with self._lock:
            users = self._load_users()
            if username in users:
                return False, "Username already exists"
            if any(u.email == email for u in users.values()):
                return False, "Email already exists"
            users[username] = User(username, password, email)
            self._save_users(users)
        return True, "User created successfully"

    def get_user(self, username: str):
        return self._load_users().get((username or "").strip())

    def save_user(self, user: User):
        with self._lock:
            users = self._load_users()
            users[user.username] = user
            self._save_users(users)

    def get_user_by_email(self, email: str):
        email = (email or "").strip().lower()
        for user in self._load_users().values():
            if user.email == email:
                return user
        return None

    def get_user_by_public_key(self, public_key: str):
        public_key = (public_key or "").strip()
        if not public_key:
            return None
        for user in self._load_users().values():
            if user.public_key == public_key:
                return user
        return None

    def set_user_public_key(self, username: str, public_key: str) -> bool:
        user = self.get_user(username)
        if not user:
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

    def delete_user(self, username: str) -> bool:
        username = (username or "").strip()
        if not username:
            return False
        with self._lock:
            users = self._load_users()
            if username not in users:
                return False
            del users[username]
            self._save_users(users)
        return True

    def delete_user_assets(self, username: str):
        username = (username or "").strip()
        if not username:
            return
        with self._lock:
            market = self._load_marketplace()
            market.pop(username, None)
            self._save_marketplace(market)

    # ── Marketplace ───────────────────────────────────────────────────────────

    def _load_marketplace(self) -> dict:
        """Load marketplace, migrating old fields and deduplicating by asset_id (keep highest version)."""
        try:
            raw = json.loads(self.marketplace_json_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            result = {}
            for owner, items in raw.items():
                if not isinstance(items, list):
                    continue
                by_id: dict[str, dict] = {}
                for i in items:
                    if not isinstance(i, dict):
                        continue
                    item_dict = MarketplaceItem.from_dict(i).to_dict()
                    aid = item_dict.get("asset_id", "")
                    if not aid:
                        continue
                    existing = by_id.get(aid)
                    if existing is None or int(item_dict.get("version", 0)) > int(existing.get("version", 0)):
                        by_id[aid] = item_dict
                result[str(owner)] = list(by_id.values())
            return result
        except Exception:
            return {}

    def _save_marketplace(self, market: dict):
        self.marketplace_json_path.write_text(
            json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_asset(self, username: str, asset: MarketplaceItem) -> bool:
        with self._lock:
            market = self._load_marketplace()
            market.setdefault(username, [])
            market[username].append(asset.to_dict())
            self._save_marketplace(market)
        return True

    def get_all_assets(self) -> list[MarketplaceItem]:
        market = self._load_marketplace()
        assets = [MarketplaceItem.from_dict(a) for items in market.values() for a in items]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_all_for_sale_assets(self) -> list[MarketplaceItem]:
        """Return all FOR_SALE assets regardless of owner."""
        market = self._load_marketplace()
        assets = [
            MarketplaceItem.from_dict(a)
            for items in market.values()
            for a in items if isinstance(a, dict)
        ]
        assets = [a for a in assets if a.asset_status == ASSET_STATUS_FOR_SALE]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_all_for_sale_asset_ids(self) -> list[dict]:
        return [{"id": a.asset_id, "version": a.version} for a in self.get_all_for_sale_assets() if a.asset_id]

    def update_asset_status(self, asset_id: str, status: str,
                            increment_version: bool = False) -> bool:
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return False
        with self._lock:
            market = self._load_marketplace()
            for owner_items in market.values():
                for item_dict in owner_items:
                    if isinstance(item_dict, dict) and item_dict.get("asset_id") == asset_id:
                        item_dict["asset_status"] = status
                        if increment_version:
                            item_dict["version"] = int(item_dict.get("version", 1)) + 1
                        self._save_marketplace(market)
                        return True
        return False

    def transfer_asset(self, asset_id: str, from_owner: str, to_owner: str) -> bool:
        """Move asset from seller to buyer after a successful blockchain purchase."""
        asset_id = (asset_id or "").strip()
        from_owner = (from_owner or "").strip()
        to_owner = (to_owner or "").strip()
        if not asset_id or not from_owner or not to_owner:
            return False
        with self._lock:
            market = self._load_marketplace()
            from_list = market.get(from_owner, [])
            asset_dict = None
            new_from_list = []
            for item in from_list:
                if isinstance(item, dict) and item.get("asset_id") == asset_id:
                    asset_dict = dict(item)
                else:
                    new_from_list.append(item)
            if asset_dict is None:
                return False
            market[from_owner] = new_from_list
            asset_dict["owner"] = to_owner
            asset_dict["asset_status"] = ASSET_STATUS_UNLISTED
            asset_dict["version"] = int(asset_dict.get("version", 1)) + 1
            market.setdefault(to_owner, [])
            market[to_owner].append(asset_dict)
            self._save_marketplace(market)
        return True

    def delete_asset(self, asset_id: str, owner: str) -> bool:
        """Remove asset from DB entirely (no blockchain change)."""
        asset_id = (asset_id or "").strip()
        owner = (owner or "").strip()
        if not asset_id or not owner:
            return False
        with self._lock:
            market = self._load_marketplace()
            items = market.get(owner, [])
            new_items = [
                d for d in items
                if not (isinstance(d, dict) and d.get("asset_id") == asset_id)
            ]
            if len(new_items) == len(items):
                return False
            market[owner] = new_items
            self._save_marketplace(market)
        return True

    def get_assets_for_user(self, username: str) -> list[MarketplaceItem]:
        """Return assets owned by user that are NOT currently on the marketplace (not FOR_SALE)."""
        username = (username or "").strip()
        if not username:
            return []
        market = self._load_marketplace()
        assets = [MarketplaceItem.from_dict(a) for a in market.get(username, []) if isinstance(a, dict)]
        assets = [a for a in assets if a.asset_status != ASSET_STATUS_FOR_SALE]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def find_asset_by_id(self, asset_id: str):
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return None
        for items in self._load_marketplace().values():
            for d in items:
                if isinstance(d, dict) and d.get("asset_id") == asset_id:
                    return MarketplaceItem.from_dict(d)
        return None

    # ── Notifications ─────────────────────────────────────────────────────────

    def _load_notifications(self) -> dict:
        try:
            data = json.loads(self.notifications_json_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_notifications(self, data: dict):
        self.notifications_json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def queue_notification(self, username: str, msg: str):
        username = str(username or "").strip()
        if not username:
            return
        with self._lock:
            data = self._load_notifications()
            items = data.get(username, [])
            if not isinstance(items, list):
                items = []
            items.append({"msg": str(msg)})
            data[username] = items
            self._save_notifications(data)

    def flush_notifications(self, username: str) -> list[str]:
        """Return and clear all queued notifications for the user."""
        username = str(username or "").strip()
        if not username:
            return []
        with self._lock:
            data = self._load_notifications()
            items = data.get(username, [])
            data[username] = []
            self._save_notifications(data)
        if not isinstance(items, list):
            return []
        return [str(i.get("msg", "")) if isinstance(i, dict) else str(i) for i in items if i]
