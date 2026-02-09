"""
Blockchain models: Transaction and Block.
Used by RPC (make_transaction) and nodes (ledger, gossip).
"""

import json
from datetime import datetime


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
        self.transactions = list(transactions) if transactions else []

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
            'transactions': [t if isinstance(t, dict) else t.to_mempool_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return cls()
        tx_list = d.get('transactions', [])
        return cls(
            index=d.get('index', 0),
            timestamp=d.get('timestamp'),
            prev_hash=d.get('prev_hash', ''),
            current_hash=d.get('current_hash', ''),
            nonce=d.get('nonce', 0),
            miner_id=d.get('miner_id', ''),
            signature=d.get('signature', ''),
            public_key_pem=d.get('public_key_pem', ''),
            transactions=tx_list,
        )
