"""
Blockchain classes: Transaction, Block, Ledger, Notification.
All persisted using pickle.
"""

import pickle
import os
from datetime import datetime
from pathlib import Path


class Transaction:
    """A single transaction: sender, payload, signature, and timestamps for ledger."""

    def __init__(self, sender='', data=None, signature='', start_timestamp=None, end_timestamp=None):
        self.sender = sender
        self.data = data if data is not None else {}
        self.signature = signature
        self.start_timestamp = start_timestamp or datetime.utcnow().isoformat()
        self.end_timestamp = end_timestamp  # set when block is written

    def to_dict(self):
        return {
            'sender': self.sender,
            'data': self.data,
            'signature': self.signature,
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
            start_timestamp=d.get('start_timestamp'),
            end_timestamp=d.get('end_timestamp'),
        )

    def to_mempool_dict(self):
        """Payload used when adding to mempool / sending NEW_TRANSACTION (no end_timestamp yet)."""
        return {'sender': self.sender, 'data': self.data, 'signature': self.signature}


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
    """The blockchain ledger: list of blocks, persisted to pickle."""

    def __init__(self, pickle_path='ledger.pickle'):
        self.blocks = []
        self.pickle_path = Path(__file__).parent / pickle_path
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
        with open(self.pickle_path, 'wb') as f:
            pickle.dump(self.blocks, f)

    def load(self):
        if self.pickle_path.exists():
            with open(self.pickle_path, 'rb') as f:
                self.blocks = pickle.load(f)
        else:
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
            with open(self.pickle_path, 'rb') as f:
                self.notifications, self.next_id = pickle.load(f)
        else:
            self.notifications = []
            self.next_id = 1