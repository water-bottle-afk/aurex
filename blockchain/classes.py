"""
Blockchain classes: Transaction, Block, Ledger, Notification.
Ledgers are persisted as JSON; notifications remain persisted via pickle.
"""

import json
import pickle
from datetime import datetime
from pathlib import Path
from decimal import Decimal


class Transaction:
    """A single transaction: sender, payload, signature, and timestamps for ledger."""

    def __init__(self, sender='', data=None, signature='', public_key='', start_timestamp=None, end_timestamp=None):
        self.sender = sender
        self.data = data if data is not None else {}
        self.signature = signature
        self.public_key = public_key
        self.start_timestamp = start_timestamp or datetime.utcnow().isoformat()
        self.end_timestamp = end_timestamp  # set when block is written

    def to_dict(self):
        return {
            'sender': self.sender,
            'data': self.data,
            'signature': self.signature,
            'public_key': self.public_key,
            'start_timestamp': self.start_timestamp,
            'end_timestamp': self.end_timestamp,
        }

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return cls()
        return cls(
            sender=d.get('sender', ''),
            data=d.get('data', d),
            signature=d.get('signature', ''),
            public_key=d.get('public_key', ''),
            start_timestamp=d.get('start_timestamp'),
            end_timestamp=d.get('end_timestamp'),
        )

    def to_mempool_dict(self):
        """Payload used when adding to mempool / sending NEW_TRANSACTION (no end_timestamp yet)."""
        return {
            'sender': self.sender,
            'data': self.data,
            'signature': self.signature,
            'public_key': self.public_key,
        }


class StateManager:
    """
    Deterministic chain state for a node.
    balances: Public_Key -> int (minor units; 1 token = 100 units)
    ownership: Image_Hash -> Owner_Public_Key
    """

    MINOR_UNITS = Decimal("100")
    INITIAL_COINS = Decimal("100")
    INITIAL_BALANCE_INT = int(INITIAL_COINS * MINOR_UNITS)

    def __init__(self, balances=None, ownership=None):
        self.balances = dict(balances or {})
        self.ownership = dict(ownership or {})

    def copy(self):
        return StateManager(self.balances.copy(), self.ownership.copy())

    @staticmethod
    def amount_to_int(value):
        """Convert user-facing amount to deterministic int minor units."""
        if value in (None, ''):
            raise ValueError("missing amount")
        dec = Decimal(str(value))
        scaled = dec * StateManager.MINOR_UNITS
        if scaled != scaled.to_integral_value():
            raise ValueError("amount precision unsupported")
        return int(scaled)

    def get_balance(self, public_key):
        if not public_key:
            return 0
        return int(self.balances.get(public_key, self.INITIAL_BALANCE_INT))

    def _ensure_account(self, public_key):
        if public_key and public_key not in self.balances:
            self.balances[public_key] = self.INITIAL_BALANCE_INT

    def set_balance(self, public_key, amount_int):
        self.balances[public_key] = int(amount_int)

    def validate_mint(self, image_hash, owner_public_key):
        if not image_hash:
            return False, "mint missing image_hash"
        if not owner_public_key:
            return False, "mint missing owner key"
        if image_hash in self.ownership:
            return False, "image already minted"
        return True, "ok"

    def validate_trade(self, image_hash, buyer_public_key, seller_public_key, price_int):
        if not image_hash:
            return False, "trade missing image_hash"
        if not buyer_public_key or not seller_public_key:
            return False, "trade missing buyer/seller key"
        if buyer_public_key == seller_public_key:
            return False, "buyer cannot equal seller"
        if int(price_int) <= 0:
            return False, "trade price must be positive"
        owner = self.ownership.get(image_hash)
        if owner != seller_public_key:
            return False, "seller does not own image"
        if self.get_balance(buyer_public_key) < int(price_int):
            return False, "insufficient balance"
        return True, "ok"

    def apply_mint(self, image_hash, owner_public_key):
        ok, reason = self.validate_mint(image_hash, owner_public_key)
        if not ok:
            return False, reason
        self._ensure_account(owner_public_key)
        self.ownership[image_hash] = owner_public_key
        return True, "ok"

    def apply_trade(self, image_hash, buyer_public_key, seller_public_key, price_int):
        ok, reason = self.validate_trade(image_hash, buyer_public_key, seller_public_key, price_int)
        if not ok:
            return False, reason
        price_int = int(price_int)
        self._ensure_account(buyer_public_key)
        self._ensure_account(seller_public_key)
        self.balances[buyer_public_key] = self.get_balance(buyer_public_key) - price_int
        self.balances[seller_public_key] = self.get_balance(seller_public_key) + price_int
        self.ownership[image_hash] = buyer_public_key
        return True, "ok"


class Block:
    """A mined block: index, hashes, nonce, miner, signature, transactions."""

    def __init__(self, index=0, timestamp=None, prev_hash='', current_hash='', nonce=0,
                 miner_id='', signature='', public_key_pem='', transactions=None):
        self.index = index
        self.timestamp = timestamp or datetime.utcnow().isoformat()
        self.prev_hash = prev_hash
        self.current_hash = current_hash
        self.nonce = nonce
        self.miner_id = miner_id
        self.signature = signature
        self.public_key_pem = public_key_pem
        self.transactions = transactions or []

    def to_dict(self):
        return {
            'index': self.index,
            'timestamp': self.timestamp,
            'prev_hash': self.prev_hash,
            'current_hash': self.current_hash,
            'nonce': self.nonce,
            'miner_id': self.miner_id,
            'signature': self.signature,
            'public_key_pem': self.public_key_pem,
            'transactions': [tx.to_dict() for tx in self.transactions],
        }

    @classmethod
    def from_dict(cls, d):
        transactions = [Transaction.from_dict(tx) for tx in d.get('transactions', [])]
        return cls(
            index=d.get('index', 0),
            timestamp=d.get('timestamp'),
            prev_hash=d.get('prev_hash', ''),
            current_hash=d.get('current_hash', ''),
            nonce=d.get('nonce', 0),
            miner_id=d.get('miner_id', ''),
            signature=d.get('signature', ''),
            public_key_pem=d.get('public_key_pem', ''),
            transactions=transactions,
        )


class Ledger:
    """The blockchain ledger: list of blocks, persisted to JSON."""

    def __init__(self, ledger_path='ledger.json'):
        self.blocks = []
        path = Path(ledger_path)
        if not path.is_absolute():
            path = Path(__file__).parent / path
        self.ledger_path = path
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    def add_block(self, block):
        self.blocks.append(block)
        self.save()

    def get_last_block(self):
        return self.blocks[-1] if self.blocks else None

    def get_last_hash(self):
        last = self.get_last_block()
        return last.current_hash if last else '0'

    def get_block_by_index(self, index):
        for block in self.blocks:
            if block.index == index:
                return block
        return None

    def save(self):
        payload = [block.to_dict() for block in self.blocks]
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def load(self):
        if self.ledger_path.exists():
            try:
                with open(self.ledger_path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or []
                self.blocks = [Block.from_dict(d) for d in data]
                return
            except Exception:
                self.blocks = []

        # Migrate legacy pickle if present
        legacy_path = self.ledger_path.with_suffix('.pickle')
        if legacy_path.exists():
            try:
                with open(legacy_path, 'rb') as f:
                    self.blocks = pickle.load(f)
                self.save()
            except Exception:
                self.blocks = []


class Notification:
    """A notification: id, username, title, body, type, etc."""

    def __init__(self, id=None, username='', title='', body='', notif_type='system', asset_id=None, tx_id=None, is_read=False, created_at=None):
        self.id = id
        self.username = username
        self.title = title
        self.body = body
        self.notif_type = notif_type
        self.asset_id = asset_id
        self.tx_id = tx_id
        self.is_read = is_read
        self.created_at = created_at or datetime.utcnow().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'title': self.title,
            'body': self.body,
            'type': self.notif_type,
            'asset_id': self.asset_id,
            'tx_id': self.tx_id,
            'is_read': self.is_read,
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d.get('id'),
            username=d.get('username', ''),
            title=d.get('title', ''),
            body=d.get('body', ''),
            notif_type=d.get('type', 'system'),
            asset_id=d.get('asset_id'),
            tx_id=d.get('tx_id'),
            is_read=d.get('is_read', False),
            created_at=d.get('created_at'),
        )


class NotificationsManager:
    """Manages notifications, persisted to pickle."""

    def __init__(self, pickle_path='notifications.pickle'):
        self.notifications = []
        self.pickle_path = Path(__file__).parent / pickle_path
        self.next_id = 1
        self.load()

    def create_notification(self, username, title, body, notif_type='system', asset_id=None, tx_id=None):
        notif = Notification(
            id=self.next_id,
            username=username,
            title=title,
            body=body,
            notif_type=notif_type,
            asset_id=asset_id,
            tx_id=tx_id,
        )
        self.notifications.append(notif)
        self.next_id += 1
        self.save()
        return notif

    def get_notifications(self, username, limit=50):
        user_notifs = [n for n in self.notifications if n.username == username]
        user_notifs.sort(key=lambda n: n.created_at, reverse=True)
        return user_notifs[:limit]

    def get_unread_count(self, username):
        return sum(1 for n in self.notifications if n.username == username and not n.is_read)

    def mark_read(self, username):
        for n in self.notifications:
            if n.username == username:
                n.is_read = True
        self.save()

    def save(self):
        with open(self.pickle_path, 'wb') as f:
            pickle.dump((self.notifications, self.next_id), f)

    def load(self):
        if self.pickle_path.exists():
            try:
                with open(self.pickle_path, 'rb') as f:
                    self.notifications, self.next_id = pickle.load(f)
                return
            except Exception:
                self.notifications = []
                self.next_id = 1
                return
        self.notifications = []
        self.next_id = 1
