"""
Proof of Authority (PoA) Node
Validates blocks based on trusted authority signatures
Works on Port 13246
"""

import hashlib
import time
import logging
from config import *
from utils import (
    is_valid_data, is_valid_block, validate_signature_format,
    create_signature, log_block_added
)

logger = logging.getLogger(__name__)


class PoANode:
    """Proof of Authority Node - Signs and validates blocks"""
    
    # ========================================================================
    # INITIALIZATION
    # ========================================================================
    
    def __init__(self, node_id, is_authority=False):
        """Initialize PoA Node"""
        self.node_id = node_id
        self.is_authority = is_authority
        self.chain = []
        self.pending_blocks = []
        role = "Authority" if is_authority else "Regular Node"
        logger.info(f"[{self.node_id}] PoA Node initialized ({role})")
    
    # ========================================================================
    # SIGNING OPERATIONS
    # ========================================================================
    
    def sign_data(self, data):
        """Sign data if node is authority"""
        if not self.is_authority:
            logger.warning(f"[{self.node_id}] {ERROR_UNAUTHORIZED_NODE}")
            return None
        
        if not is_valid_data(data):
            logger.error(f"[{self.node_id}] {ERROR_INVALID_DATA}")
            return None
        
        try:
            signature = create_signature(self.node_id, data)
            logger.info(f"[{self.node_id}] Data signed: {signature[:20]}...")
            return signature
        except Exception as e:
            logger.error(f"[{self.node_id}] Error signing data: {e}", exc_info=True)
            return None
    
    def validate_signature(self, node_id, signature):
        """Validate signature format"""
        if not signature or not validate_signature_format(node_id, signature):
            logger.warning(f"[{self.node_id}] {ERROR_INVALID_SIGNATURE} from {node_id}")
            return False
        
        logger.debug(f"[{self.node_id}] Signature valid from {node_id}")
        return True
    
    # ========================================================================
    # BLOCK MANAGEMENT
    # ========================================================================
    
    def create_block(self, data, signer_id, signature=None, previous_hash=None):
        """Create a PoA block"""
        block = {
            BLOCK_FIELD_INDEX: len(self.chain),
            BLOCK_FIELD_TIMESTAMP: time.time(),
            BLOCK_FIELD_DATA: data,
            BLOCK_FIELD_PREVIOUS_HASH: previous_hash,
            BLOCK_FIELD_SIGNER_ID: signer_id,
            BLOCK_FIELD_SIGNATURE: signature,
            BLOCK_FIELD_HASH: hashlib.sha256(str(data).encode()).hexdigest(),
        }
        logger.debug(f"[{self.node_id}] PoA block created")
        return block
    
    def add_block(self, block):
        """Add validated block to chain"""
        required_fields = [
            BLOCK_FIELD_DATA,
            BLOCK_FIELD_PREVIOUS_HASH,
            BLOCK_FIELD_SIGNER_ID,
            BLOCK_FIELD_SIGNATURE
        ]
        
        is_valid, missing = is_valid_block(block, required_fields)
        if not is_valid:
            logger.error(f"[{self.node_id}] {ERROR_INVALID_BLOCK} (missing: {missing})")
            return False
        
        try:
            self.chain.append(block)
            log_block_added(self.node_id, len(self.chain))
            return True
        except Exception as e:
            logger.error(f"[{self.node_id}] Error adding block: {e}", exc_info=True)
            return False
    
    # ========================================================================
    # PENDING BLOCK MANAGEMENT
    # ========================================================================
    
    def add_pending_block(self, block):
        """Add block to pending list"""
        if not block or not isinstance(block, dict):
            logger.error(f"[{self.node_id}] Invalid pending block")
            return False
        
        self.pending_blocks.append(block)
        logger.debug(f"[{self.node_id}] Block added to pending ({len(self.pending_blocks)})")
        return True
    
    def get_pending_blocks(self):
        """Get all pending blocks"""
        return self.pending_blocks.copy()
    
    def clear_pending_blocks(self):
        """Clear pending blocks"""
        self.pending_blocks.clear()
    
    # ========================================================================
    # CHAIN OPERATIONS
    # ========================================================================
    
    def get_chain_length(self):
        """Get chain length"""
        return len(self.chain)
    
    def get_last_block(self):
        """Get last block"""
        return self.chain[-1] if self.chain else None
    
    def get_chain_copy(self):
        """Get copy of blockchain"""
        return self.chain.copy()
    
    def get_chain_info(self):
        """Get chain information"""
        return {
            'node_id': self.node_id,
            'is_authority': self.is_authority,
            'chain_length': len(self.chain),
            'pending_blocks': len(self.pending_blocks)
        }
