"""
Proof of Work (PoW) Node
Competes in a race to find a hash with required leading zeros
Works on Port 13245
"""

import hashlib
import time
import logging
from config import *
from utils import (
    is_valid_data, is_valid_block, check_hash_difficulty,
    create_hash_target, log_block_solution, log_mining_progress,
    log_block_added
)

logger = logging.getLogger(__name__)


class PoWNode:
    """Proof of Work Node - Solves hash puzzles"""
    
    # ========================================================================
    # INITIALIZATION
    # ========================================================================
    
    def __init__(self, node_id, difficulty=DEFAULT_POW_DIFFICULTY):
        """Initialize PoW Node"""
        self.node_id = node_id
        self.difficulty = difficulty
        self.chain = []
        self.is_mining = False
        logger.info(f"[{self.node_id}] PoW Node initialized (difficulty={difficulty})")
    
    # ========================================================================
    # MINING OPERATIONS
    # ========================================================================
    
    def solve(self, data):
        """Solve PoW puzzle - find nonce with required leading zeros"""
        if not is_valid_data(data):
            logger.error(f"[{self.node_id}] {ERROR_INVALID_DATA}")
            return None, None
        
        try:
            return self._mine_puzzle(data)
        except Exception as e:
            logger.error(f"[{self.node_id}] Error in solve: {e}", exc_info=True)
            return None, None
    
    def _mine_puzzle(self, data):
        """Internal mining loop"""
        nonce = MIN_NONCE
        start_time = time.time()
        
        while self.is_mining:
            hash_value = self._compute_hash(data, nonce)
            
            if check_hash_difficulty(hash_value, self.difficulty):
                elapsed_time = time.time() - start_time
                log_block_solution(self.node_id, hash_value, nonce, elapsed_time)
                return hash_value, nonce
            
            nonce += 1
            
            if nonce % MINING_PROGRESS_INTERVAL == 0:
                log_mining_progress(self.node_id, nonce)
        
        return None, None
    
    def _compute_hash(self, data, nonce):
        """Compute SHA256 hash"""
        target = create_hash_target(data, nonce)
        return hashlib.sha256(target).hexdigest()
    
    # ========================================================================
    # BLOCK MANAGEMENT
    # ========================================================================
    
    def create_block(self, data, previous_hash=None, nonce=0, hash_value=None):
        """Create a new PoW block"""
        block = {
            BLOCK_FIELD_INDEX: len(self.chain),
            BLOCK_FIELD_TIMESTAMP: time.time(),
            BLOCK_FIELD_DATA: data,
            BLOCK_FIELD_PREVIOUS_HASH: previous_hash,
            BLOCK_FIELD_NONCE: nonce,
            BLOCK_FIELD_HASH: hash_value,
        }
        logger.debug(f"[{self.node_id}] Block created")
        return block
    
    def add_block(self, block):
        """Add block to chain"""
        is_valid, missing_fields = is_valid_block(block, [BLOCK_FIELD_HASH, BLOCK_FIELD_NONCE])
        if not is_valid:
            logger.error(f"[{self.node_id}] {ERROR_INVALID_BLOCK}")
            return False
        
        try:
            self.chain.append(block)
            log_block_added(self.node_id, len(self.chain))
            return True
        except Exception as e:
            logger.error(f"[{self.node_id}] Error adding block: {e}", exc_info=True)
            return False
    
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
