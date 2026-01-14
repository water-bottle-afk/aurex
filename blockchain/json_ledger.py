"""
JSON Ledger - Simple file-based blockchain storage
Stores blocks in a human-readable JSON format
"""

import json
import os
from datetime import datetime


class JSONLedger:
    """Manages blockchain ledger in JSON format"""
    
    def __init__(self, filepath='ledger.json'):
        """Initialize JSON ledger"""
        self.filepath = filepath
        self.ledger = self._load_ledger()
    
    def _load_ledger(self):
        """Load ledger from JSON file"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except:
                return {'blocks': [], 'transactions': []}
        return {'blocks': [], 'transactions': []}
    
    def _save_ledger(self):
        """Save ledger to JSON file"""
        with open(self.filepath, 'w') as f:
            json.dump(self.ledger, f, indent=2)
    
    def add_block(self, block_hash, nonce, miner_id, difficulty, data, previous_hash=None, signature=None, public_key=None):
        """Add a new block to the ledger with optional signature"""
        block = {
            'id': len(self.ledger['blocks']) + 1,
            'timestamp': datetime.now().isoformat(),
            'block_hash': block_hash,
            'previous_hash': previous_hash or '0' * 64,
            'nonce': nonce,
            'miner_id': miner_id,
            'difficulty': difficulty,
            'data': data,
            'signature': signature,
            'public_key': public_key
        }
        
        self.ledger['blocks'].append(block)
        self._save_ledger()
        
        print(f"📝 Block #{block['id']} saved to ledger")
        return block
    
    def add_transaction(self, tx_hash, tx_data):
        """Add transaction to ledger"""
        transaction = {
            'hash': tx_hash,
            'timestamp': datetime.now().isoformat(),
            'data': tx_data
        }
        
        self.ledger['transactions'].append(transaction)
        self._save_ledger()
        
        return transaction
    
    def get_last_blocks(self, count=2):
        """Get last N blocks"""
        return self.ledger['blocks'][-count:]
    
    def get_all_blocks(self):
        """Get all blocks"""
        return self.ledger['blocks']
    
    def print_ledger(self):
        """Print the last 2 blocks in readable format with signature verification"""
        from key_manager import NodeKeyManager
        
        blocks = self.get_last_blocks(2)
        
        if not blocks:
            print("\n[LEDGER] No blocks yet\n")
            return
        
        print("\n" + "="*80)
        print("⛓️  BLOCKCHAIN LEDGER - LAST 2 BLOCKS")
        print("="*80 + "\n")
        
        for block in blocks:
            print(f"📦 BLOCK #{block['id']}")
            print("─" * 80)
            print(f"  Timestamp:     {block['timestamp']}")
            print(f"  Miner:         {block['miner_id']}")
            print(f"  Difficulty:    {block['difficulty']} leading zeros")
            print(f"  Nonce:         {block['nonce']}")
            print()
            print(f"  📋 DATA:")
            data_str = str(block['data'])[:70]
            print(f"     {data_str}{'...' if len(str(block['data'])) > 70 else ''}")
            print()
            print(f"  🔐 HASH (Current Block):")
            print(f"     {block['block_hash']}")
            print()
            print(f"  ⛓️  LINKED TO PREVIOUS:")
            if block['previous_hash'] != '0' * 64:
                print(f"     {block['previous_hash']}")
            else:
                print(f"     [GENESIS BLOCK]")
            print()
            print(f"  ✍️  DIGITAL SIGNATURE:")
            if block.get('signature') and block.get('public_key'):
                # Verify signature
                is_valid = NodeKeyManager.verify_signature(
                    block['public_key'],
                    block['block_hash'],
                    block['signature']
                )
                status = "✅ VERIFIED" if is_valid else "❌ INVALID"
                print(f"     Status: {status}")
                print(f"     Signature: {block['signature'][:32]}...")
            else:
                print(f"     Status: ⚠️  UNSIGNED")
            print()
        
        print("="*80 + "\n")
    
    def export_view(self):
        """Export readable ledger view"""
        return json.dumps(self.ledger, indent=2)


# Global ledger instance
_ledger = None

def get_ledger():
    """Get or create global ledger instance"""
    global _ledger
    if _ledger is None:
        _ledger = JSONLedger('ledger.json')
    return _ledger


def reset_ledger():
    """Reset ledger (for testing)"""
    global _ledger
    _ledger = JSONLedger('ledger.json')
    _ledger.ledger = {'blocks': [], 'transactions': []}
    _ledger._save_ledger()
